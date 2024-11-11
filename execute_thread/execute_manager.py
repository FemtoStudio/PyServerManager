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
            if system == "Windows":
                full_cmd = (
                    f'start /WAIT cmd.exe /k "cd /d {self.script_dir} & '
                    f'title {self.terminal_title} & {activation_cmd}{self.cmd}"'
                )
            elif system in ["Linux", "Darwin"]:
                terminal_emulator = self._detect_terminal_emulator()
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
            full_cmd = f"{activation_cmd}{self.cmd}"

        return full_cmd

    def _get_activation_cmd(self, system):
        if not self.custom_activation_script:
            return ""
        if system == "Windows":
            return f'call "{self.custom_activation_script}" & '
        else:
            return f'source "{self.custom_activation_script}"; '

    def _detect_terminal_emulator(self):
        for emulator in ["gnome-terminal", "konsole", "xterm", "mate-terminal"]:
            if shutil.which(emulator):
                return emulator
        raise EnvironmentError("No supported terminal emulator found.")


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

        self.output = None  # Initialize output attribute
        self.error = None  # Initialize error attribute
        self.parsed_output = None

        self.logger = custom_logger or logger

        if not os.path.isfile(self.python_exe) or not os.access(self.python_exe, os.X_OK):
            raise FileNotFoundError(f"Invalid python executable: {self.python_exe}")
        if not os.path.isfile(self.script_path):
            raise FileNotFoundError(f"Script not found: {self.script_path}")

    @property
    def cmd(self) -> str:
        if self._cmd:
            return self._cmd

        serialized_args = json.dumps(self.args)
        encoded_args = base64.b64encode(serialized_args.encode("utf-8")).decode("utf-8")
        cmd_parts = [
            f'"{self.python_exe}"',
            f'"{self.script_path}"',
            f'--encoded-args "{encoded_args}"',
        ]
        main_cmd = " ".join(cmd_parts)

        cmd_list = []
        if self.pre_cmd:
            cmd_list.append(self.pre_cmd)
        cmd_list.append(main_cmd)
        if self.post_cmd:
            cmd_list.append(self.post_cmd)

        cmd_separator = self.get_command_separator()
        self._cmd = cmd_separator.join(cmd_list)
        return self._cmd

    def get_command_separator(self) -> str:
        system = platform.system()
        return " & " if system == "Windows" else " ; "

    @property
    def terminal_title(self):
        title = "Execution Terminal"
        if isinstance(self.open_new_terminal, str):
            title += self.open_new_terminal
        return title.replace(" ", "_")

    def run_noPrint(self):
        script_dir = os.path.dirname(os.path.abspath(self.script_path))
        command_builder = CommandBuilder(
            script_dir,
            self.cmd,
            self.terminal_title,
            self.open_new_terminal,
            self.custom_activation_script,
        )
        full_cmd = command_builder.build()
        env = os.environ.copy()
        env.update(self.export_env)

        try:
            if self.open_new_terminal:
                # Cannot capture output in a new terminal
                self.logger.info(f"Executing command in new terminal: {full_cmd}")
                if platform.system() == "Windows":
                    self.terminal = subprocess.Popen(
                        full_cmd, shell=True, env=env, creationflags=subprocess.DETACHED_PROCESS
                    )
                else:
                    self.terminal = subprocess.Popen(full_cmd, env=env)
                self.terminal.wait()
            else:
                # Running in the same terminal, capture output
                self.logger.info(f"Executing command in the same terminal: {full_cmd}")
                if platform.system() == "Windows":
                    self.process = subprocess.Popen(
                        full_cmd, shell=True, env=env,
                        stdout=subprocess.PIPE, stderr=subprocess.PIPE
                    )
                else:
                    self.process = subprocess.Popen(
                        full_cmd, shell=True, env=env, preexec_fn=os.setsid,
                        stdout=subprocess.PIPE, stderr=subprocess.PIPE
                    )
                # Capture output and error
                stdout, stderr = self.process.communicate()
                self.output = stdout.decode('utf-8') if stdout else ''
                self.error = stderr.decode('utf-8') if stderr else ''
                self.parsed_output = self.parse_encoded_output(self.output)

        except Exception as e:
            self.logger.exception("An error occurred during execution.")
            self.error = str(e)
        finally:
            if self.callback:
                try:
                    self.callback(self)
                except Exception as e:
                    self.logger.exception("An error occurred in the callback.")

    def run(self):
        script_dir = os.path.dirname(os.path.abspath(self.script_path))
        command_builder = CommandBuilder(
            script_dir,
            self.cmd,
            self.terminal_title,
            self.open_new_terminal,
            self.custom_activation_script,
        )
        full_cmd = command_builder.build()
        env = os.environ.copy()
        env.update(self.export_env)
        env['PYTHONUNBUFFERED'] = '1'  # Add this line

        try:
            if self.open_new_terminal:
                # Cannot capture output in a new terminal
                self.logger.info(f"Executing command in new terminal")
                if platform.system() == "Windows":
                    self.terminal = subprocess.Popen(
                        full_cmd, shell=True, env=env, creationflags=subprocess.DETACHED_PROCESS
                    )
                else:
                    self.terminal = subprocess.Popen(full_cmd, env=env)
                self.terminal.wait()
            else:
                # Running in the same terminal, capture output
                self.logger.info(f"Executing command in the same terminal")
                self.output = ''
                if platform.system() == "Windows":
                    self.process = subprocess.Popen(
                        full_cmd, shell=True, env=env,
                        stdout=subprocess.PIPE, bufsize=1, universal_newlines=True
                    )
                else:
                    self.process = subprocess.Popen(
                        full_cmd, shell=True, env=env, preexec_fn=os.setsid,
                        stdout=subprocess.PIPE, bufsize=1, universal_newlines=True
                    )
                # Read output in real time without extra threads
                for line in self.process.stdout:
                    self.output += line
                    # self.logger.info(line.rstrip('\n'))  # Print to console immediately
                    self.logger.info(line)  # Log the line as is
                self.process.wait()
                self.parsed_output = self.parse_encoded_output(self.output)
        except Exception as e:
            self.logger.exception("An error occurred during execution.")
            self.error = str(e)
        finally:
            if self.callback:
                try:
                    self.callback(self)
                except Exception as e:
                    self.logger.exception("An error occurred in the callback.")

    def parse_encoded_output(self, stdout_str):
        """
        Parses the stdout string to find the encoded output.

        Returns the decoded output dictionary, or None if not found.
        """
        start_index = stdout_str.find(self.OUTPUT_PREFIX)
        end_index = stdout_str.find(self.OUTPUT_SUFFIX, start_index)
        if start_index != -1 and end_index != -1:
            start_index += len(self.OUTPUT_PREFIX)
            encoded_output = stdout_str[start_index:end_index]
            try:
                decoded_output_json = base64.b64decode(encoded_output).decode('utf-8')
                output_dict = json.loads(decoded_output_json)
                return output_dict
            except (base64.binascii.Error, json.JSONDecodeError) as e:
                self.logger.exception(f"Failed to decode output. {e}")
                return None
        else:
            return None

    def terminate(self):
        """
        Terminates the execution thread. If a process or terminal is associated with the thread, it terminates them as well.
        """
        if self.process:
            self.logger.info(f'Terminating process {self.process.pid}')
            if platform.system() == "Windows":
                parent = psutil.Process(self.process.pid)
                for child in parent.children(recursive=True):
                    child.terminate()
                parent.terminate()
            else:
                os.killpg(os.getpgid(self.process.pid), signal.SIGTERM)

        if self.terminal:

            self.logger.info(f'Terminating terminal {self.terminal.pid}')
            if platform.system() == "Windows":
                try:
                    terminal_process = psutil.Process(self.terminal.pid)
                    for child in terminal_process.children(recursive=True):
                        child.terminate()
                    terminal_process.terminate()
                except psutil.NoSuchProcess:
                    pass
            else:
                os.killpg(os.getpgid(self.terminal.pid), signal.SIGTERM)


class ExecuteThreadManager:
    """
    Manages the creation and tracking of ExecuteThread instances.
    """

    def __init__(
            self,
            python_exe: str,
            script_path: str,
            custom_activation_script: Optional[str] = None,
            export_env: Optional[Dict[str, str]] = None,
            callback: Optional[Callable] = None,  # Add this parameter
            custom_logger: Optional[logging.Logger] = None,
    ):
        self.logger = custom_logger or logger

        # Check if python_exe exists and is executable
        if not os.path.isfile(python_exe):
            raise FileNotFoundError(f"The specified Python executable '{python_exe}' does not exist.")
        if not os.access(python_exe, os.X_OK):
            raise PermissionError(f"The specified Python executable '{python_exe}' is not executable.")

        # Check if script_path exists
        if not os.path.isfile(script_path):
            raise FileNotFoundError(f"The specified script path '{script_path}' does not exist.")

        # Log a warning if custom_activation_script is provided but does not exist
        if custom_activation_script and not os.path.isfile(custom_activation_script):
            self.logger.warning(
                f"Custom activation script '{custom_activation_script}' does not exist. Proceeding without it.")
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
            export_env: Optional[dict] = None,
            pre_cmd: Optional[str] = None,
            post_cmd: Optional[str] = None,
            open_new_terminal: Union[bool, str] = False,
            callback: Optional[Callable] = None,  # Add this parameter

    ) -> ExecuteThread:
        """
        Creates an ExecuteThread instance with the given parameters,
        adds it to the managed threads list, and returns it.
        """
        self.script_path = script_path or self.script_path
        thread = ExecuteThread(
            python_exe=python_exe or self.python_exe,
            script_path=self.script_path,
            args=args,
            open_new_terminal=open_new_terminal,
            custom_activation_script=self.custom_activation_script,
            export_env=export_env or self.export_env,
            pre_cmd=pre_cmd,
            post_cmd=post_cmd,
            callback=callback or self.callback,  # Pass the callback
            custom_logger=self.logger

        )
        self.threads.append(thread)
        return thread

    def clean_up_threads(self):
        self.threads = [t for t in self.threads if t.is_alive()]

    def terminate_all(self):
        for thread in self.threads:
            thread.terminate()
        self.threads.clear()
