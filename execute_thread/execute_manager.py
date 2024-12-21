# execute_manager.py
import base64
import json
import logging
import os
import platform
import shutil
import signal
import subprocess
import threading
from typing import Dict, Optional, Union, List, Callable

import psutil

logger = logging.getLogger(__name__)


class CommandBuilder:
    """
    A helper class to build commands and handle platform-specific differences.
    """

    def __init__(
        self,
        script_dir: str,
        cmd: str,
        terminal_title: str,
        open_new_terminal: Union[bool, str],
        custom_activation_script: Optional[str] = None,
    ):
        self.script_dir = script_dir
        self.cmd = cmd
        self.terminal_title = terminal_title
        self.open_new_terminal = open_new_terminal
        self.custom_activation_script = custom_activation_script

    def build(self):
        """
        Builds the command based on the platform and whether to open a new terminal.
        """
        system = platform.system()
        activation_cmd = self._get_activation_cmd(system)

        if self.open_new_terminal:
            # Launch in a new terminal window
            if system == "Windows":
                # Windows: use cmd.exe, set the title, call activation script (if any), then run commands
                full_cmd = (
                    f'start /WAIT cmd.exe /k "cd /d {self.script_dir} & '
                    f'title {self.terminal_title} & {activation_cmd}{self.cmd}"'
                )
            elif system in ["Linux", "Darwin"]:
                # Linux/macOS: find a suitable terminal emulator and pass a bash -c command
                terminal_emulator = self._detect_terminal_emulator()
                # The final command in new terminal keeps the shell open with `exec bash`
                full_cmd = [
                    terminal_emulator,
                    "--title",
                    self.terminal_title,
                    "-e",
                    f'bash -c \'cd "{self.script_dir}"; {activation_cmd}{self.cmd}; exec bash\'',
                ]
            else:
                raise NotImplementedError(f"Unsupported platform: {system}")
        else:
            # Same terminal
            full_cmd = f"{activation_cmd}{self.cmd}"

        return full_cmd

    def _get_activation_cmd(self, system: str) -> str:
        if not self.custom_activation_script:
            return ""
        # If we have a custom activation script, build the needed command:
        if system == "Windows":
            # e.g. call "C:/path/to/activate.bat" & ...
            return f'call "{self.custom_activation_script}" & '
        else:
            # e.g. source "/home/user/path/to/activate.sh"; ...
            return f'source "{self.custom_activation_script}"; '

    def _detect_terminal_emulator(self) -> str:
        """
        Tries a few known terminal emulators and returns the first one found.
        """
        for emulator in ["gnome-terminal", "konsole", "xterm", "mate-terminal"]:
            if shutil.which(emulator):
                return emulator
        raise EnvironmentError("No supported terminal emulator found on this system.")


class ExecuteThread(threading.Thread):
    """
    A thread class to execute a Python script in a separate process,
    potentially in a new terminal window, with support for pre and post commands.
    """

    OUTPUT_PREFIX = '##BEGIN_ENCODED_OUTPUT##'
    OUTPUT_SUFFIX = '##END_ENCODED_OUTPUT##'

    def __init__(
        self,
        python_exe: str,
        script_path: str,
        args: Dict,
        open_new_terminal: Union[bool, str] = False,
        custom_activation_script: Optional[str] = None,
        export_env: Optional[Dict[str, str]] = None,
        pre_cmd: Optional[str] = None,
        post_cmd: Optional[str] = None,
        callback: Optional[Callable] = None,
        custom_logger: Optional[logging.Logger] = None,
    ):
        super().__init__()
        self.args = args.copy()
        self.open_new_terminal = open_new_terminal
        self.process = None
        self.terminal = None
        self._cmd = None

        self.python_exe = python_exe
        self.script_path = script_path
        self.custom_activation_script = custom_activation_script
        self.export_env = export_env or {}
        self.pre_cmd = pre_cmd
        self.post_cmd = post_cmd
        self.callback = callback

        self.output = ""  # store combined stdout/stderr
        self.error = None  # error message if something goes wrong
        self.parsed_output = None  # any structured data extracted via parse_encoded_output

        self.logger = custom_logger or logger

        # Check validity of python_exe and script_path
        if not os.path.isfile(self.python_exe) or not os.access(self.python_exe, os.X_OK):
            raise FileNotFoundError(f"Invalid Python executable: {self.python_exe}")
        if not os.path.isfile(self.script_path):
            raise FileNotFoundError(f"Script not found: {self.script_path}")

    @property
    def cmd(self) -> str:
        """
        Builds/returns the actual shell command(s) to run:
         1) optional pre_cmd
         2) any export statements
         3) the main python call with --encoded-args
         4) optional post_cmd
        """
        if self._cmd:
            return self._cmd

        # Base64-encode the JSON arguments
        serialized_args = json.dumps(self.args)
        encoded_args = base64.b64encode(serialized_args.encode("utf-8")).decode("utf-8")

        # e.g. '"C:/Python39/python.exe" "C:/my_script.py" --encoded-args "<encoded>"'
        cmd_parts = [
            f'"{self.python_exe}"',
            f'"{self.script_path}"',
            f'--encoded-args "{encoded_args}"',
        ]
        main_cmd = " ".join(cmd_parts)

        # Build the overall script to run
        cmd_list = []
        if self.pre_cmd:
            cmd_list.append(self.pre_cmd)
        if self.export_env:
            # For Windows, we do `set KEY=VALUE`; for Linux, we do `export KEY="VALUE"`
            if platform.system() == "Windows":
                for k, v in self.export_env.items():
                    cmd_list.append(f'set {k}={v}')
            else:
                for k, v in self.export_env.items():
                    cmd_list.append(f'export {k}="{v}"')
        cmd_list.append(main_cmd)

        if self.post_cmd:
            cmd_list.append(self.post_cmd)

        # On Windows, separate with &; on Linux/macOS, separate with linebreaks
        cmd_separator = self.get_command_separator()
        self._cmd = cmd_separator.join(cmd_list)
        return self._cmd

    def get_command_separator(self) -> str:
        """
        Windows typically uses ` & ` to chain commands in cmd.exe,
        whereas Linux/macOS can use line breaks or `;`.
        """
        system = platform.system()
        if system == "Windows":
            return " & "
        else:
            return "\n"

    @property
    def terminal_title(self) -> str:
        """
        If `open_new_terminal` is a string, we add that to the title.
        Otherwise, just use 'Execution Terminal'.
        """
        title = "Execution Terminal"
        if isinstance(self.open_new_terminal, str):
            title += self.open_new_terminal
        return title.replace(" ", "_")

    def run(self):
        """
        The main thread entry point. Actually spawns the subprocess in either
        a new terminal or the same terminal (capturing output).
        """
        script_dir = os.path.dirname(os.path.abspath(self.script_path))
        env = os.environ.copy()
        env.update(self.export_env)
        env['PYTHONUNBUFFERED'] = '1'  # Make sure Python output is unbuffered

        try:
            if self.open_new_terminal:
                # Launch in a new terminal window
                command_builder = CommandBuilder(
                    script_dir=script_dir,
                    cmd=self.cmd,
                    terminal_title=self.terminal_title,
                    open_new_terminal=self.open_new_terminal,
                    custom_activation_script=self.custom_activation_script,
                )
                full_cmd = command_builder.build()

                self.logger.info("Executing command in new terminal.")
                if platform.system() == "Windows":
                    # Windows new terminal
                    self.terminal = subprocess.Popen(
                        full_cmd, shell=True, env=env, creationflags=subprocess.DETACHED_PROCESS
                    )
                else:
                    # Linux/macOS new terminal
                    # full_cmd is a list: [emulator, --title, <title>, -e, "bash -c '...'"]
                    self.terminal = subprocess.Popen(full_cmd, env=env)
                self.terminal.wait()

            else:
                # Running inline (same terminal) - capture output
                self.logger.info("Executing command in the same terminal.")
                if platform.system() == "Windows":
                    # Windows inline: use cmd /c style
                    command_builder = CommandBuilder(
                        script_dir=script_dir,
                        cmd=self.cmd,
                        terminal_title=self.terminal_title,
                        open_new_terminal=False,
                        custom_activation_script=self.custom_activation_script,
                    )
                    full_cmd = command_builder.build()
                    # Here full_cmd is a string
                    self.process = subprocess.Popen(
                        full_cmd,
                        shell=True,
                        env=env,
                        stdout=subprocess.PIPE,
                        bufsize=1,
                        universal_newlines=True,
                    )

                    for line in self.process.stdout:
                        self.output += line
                        self.logger.info(line)
                    self.process.wait()

                else:
                    # Linux/macOS inline:
                    # We'll spawn /bin/bash, pass our script via stdin
                    os.chdir(script_dir)
                    self.process = subprocess.Popen(
                        ["/bin/bash"],
                        stdin=subprocess.PIPE,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.STDOUT,  # Combine stderr into stdout
                        env=env,
                        preexec_fn=os.setsid,  # so we can kill the entire process group
                        universal_newlines=True,
                    )
                    self.process.stdin.write(self.cmd)
                    self.process.stdin.close()

                    for line in self.process.stdout:
                        self.output += line
                        self.logger.info(line)
                    self.process.wait()

                # Attempt to parse structured data from the combined output
                self.parsed_output = self.parse_encoded_output(self.output)

        except Exception as e:
            self.logger.exception("An error occurred during execution.")
            self.error = str(e)
        finally:
            # Run callback if provided
            if self.callback:
                try:
                    self.callback(self)
                except Exception as callback_exc:
                    self.logger.exception("An error occurred in the callback.")

    def parse_encoded_output(self, stdout_str: str):
        """
        Looks for a block in stdout of the form:

          ##BEGIN_ENCODED_OUTPUT##<base64-encoded-json>##END_ENCODED_OUTPUT##

        If found, decodes and returns the JSON as a Python dict. Otherwise, returns None.
        """
        start_index = stdout_str.find(self.OUTPUT_PREFIX)
        end_index = stdout_str.find(self.OUTPUT_SUFFIX, start_index)

        if start_index != -1 and end_index != -1:
            start_index += len(self.OUTPUT_PREFIX)
            encoded_output = stdout_str[start_index:end_index]
            try:
                decoded_output_json = base64.b64decode(encoded_output).decode("utf-8")
                output_dict = json.loads(decoded_output_json)
                return output_dict
            except (base64.binascii.Error, json.JSONDecodeError) as decode_err:
                self.logger.exception(f"Failed to decode output. {decode_err}")
                return None
        else:
            return None

    def terminate(self):
        """
        Terminates the process or terminal if they exist.
        """
        if self.process:
            self.logger.info(f"Terminating process {self.process.pid}")
            if platform.system() == "Windows":
                # Windows kill approach
                try:
                    parent = psutil.Process(self.process.pid)
                    for child in parent.children(recursive=True):
                        child.terminate()
                    parent.terminate()
                except psutil.NoSuchProcess:
                    pass
            else:
                # Unix kill approach
                try:
                    os.killpg(os.getpgid(self.process.pid), signal.SIGTERM)
                except ProcessLookupError:
                    pass

        if self.terminal:
            self.logger.info(f"Terminating terminal {self.terminal.pid}")
            if platform.system() == "Windows":
                try:
                    terminal_process = psutil.Process(self.terminal.pid)
                    for child in terminal_process.children(recursive=True):
                        child.terminate()
                    terminal_process.terminate()
                except psutil.NoSuchProcess:
                    pass
            else:
                try:
                    os.killpg(os.getpgid(self.terminal.pid), signal.SIGTERM)
                except ProcessLookupError:
                    pass


class ExecuteThreadManager:
    """
    Manages creation and tracking of ExecuteThread instances.
    """

    def __init__(
        self,
        python_exe: str,
        script_path: str,
        custom_activation_script: Optional[str] = None,
        export_env: Optional[Dict[str, str]] = None,
        callback: Optional[Callable] = None,  # a global callback if desired
        custom_logger: Optional[logging.Logger] = None,
    ):
        self.logger = custom_logger or logger

        # Validate python_exe
        if not os.path.isfile(python_exe):
            raise FileNotFoundError(f"The specified Python executable '{python_exe}' does not exist.")
        if not os.access(python_exe, os.X_OK):
            raise PermissionError(f"The specified Python executable '{python_exe}' is not executable.")

        # Validate script_path
        if not os.path.isfile(script_path):
            raise FileNotFoundError(f"The specified script path '{script_path}' does not exist.")

        if custom_activation_script and not os.path.isfile(custom_activation_script):
            self.logger.warning(
                f"Custom activation script '{custom_activation_script}' does not exist. Proceeding without it."
            )
            custom_activation_script = None

        self.python_exe = python_exe
        self.script_path = script_path
        self.custom_activation_script = custom_activation_script
        self.export_env = export_env or {}

        self.threads: List[ExecuteThread] = []
        self.callback = callback

    def get_thread(
        self,
        args: Dict,
        python_exe: Optional[str] = None,
        script_path: Optional[str] = None,
        export_env: Optional[Dict[str, str]] = None,
        pre_cmd: Optional[str] = None,
        post_cmd: Optional[str] = None,
        open_new_terminal: Union[bool, str] = False,
        callback: Optional[Callable] = None,
    ) -> ExecuteThread:
        """
        Creates an ExecuteThread instance with the given parameters,
        adds it to the internal list, and returns it.
        """
        # If user provided an updated script_path or python_exe, use them
        effective_py = python_exe or self.python_exe
        effective_script = script_path or self.script_path
        combined_env = export_env or self.export_env

        thread = ExecuteThread(
            python_exe=effective_py,
            script_path=effective_script,
            args=args,
            open_new_terminal=open_new_terminal,
            custom_activation_script=self.custom_activation_script,
            export_env=combined_env,
            pre_cmd=pre_cmd,
            post_cmd=post_cmd,
            callback=callback or self.callback,
            custom_logger=self.logger,
        )
        self.threads.append(thread)
        return thread

    def clean_up_threads(self):
        """
        Removes finished (non-alive) threads from the internal tracking list.
        """
        self.threads = [t for t in self.threads if t.is_alive()]

    def terminate_all(self):
        """
        Terminates all running threads/processes under management.
        """
        for thread in self.threads:
            thread.terminate()
        self.threads.clear()
