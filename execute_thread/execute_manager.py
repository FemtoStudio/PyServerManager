import os
import platform
import signal
import subprocess
import threading
import base64
import json
import shutil
from typing import Dict, Optional, Union, List
import psutil
import logging

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

        try:
            if self.open_new_terminal:
                # Platform-independent command execution for a new terminal
                logger.info(f"Executing command in new terminal: {full_cmd}")
                if platform.system() == "Windows":
                    self.terminal = subprocess.Popen(
                        full_cmd, shell=True, env=env, creationflags=subprocess.DETACHED_PROCESS, stdout=subprocess.PIPE, stderr=subprocess.PIPE
                    )
                else:
                    self.terminal = subprocess.Popen(full_cmd, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                self.terminal.wait()
            else:
                # Running in the same terminal
                logger.info(f"Executing command in the same terminal: {full_cmd}")
                if platform.system() == "Windows":
                    self.process = subprocess.Popen(full_cmd, shell=True, env=env)
                else:
                    self.process = subprocess.Popen(
                        full_cmd, shell=True, env=env, preexec_fn=os.setsid
                    )

                self.process.wait()
        finally:
            pass


    def terminate(self):
        """
        Terminates the execution thread. If a process or terminal is associated with the thread, it terminates them as well.
        """
        if self.process:
            logger.info(f'Terminating process {self.process.pid}')
            if platform.system() == "Windows":
                parent = psutil.Process(self.process.pid)
                for child in parent.children(recursive=True):
                    child.terminate()
                parent.terminate()
            else:
                os.killpg(os.getpgid(self.process.pid), signal.SIGTERM)

        if self.terminal:

            logger.info(f'Terminating terminal {self.terminal.pid}')
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

    ):

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
            logger.warning(f"Custom activation script '{custom_activation_script}' does not exist. Proceeding without it.")
            custom_activation_script = None

        self.python_exe = python_exe
        self.script_path = script_path
        self.custom_activation_script = custom_activation_script
        self.export_env = export_env or {}
        self.threads: List[ExecuteThread] = []

    def get_thread(
        self,
        args: Dict,
        python_exe: Optional[str] = None,
        export_env: Optional[dict] = None,
        pre_cmd: Optional[str] = None,
        post_cmd: Optional[str] = None,
        open_new_terminal: Union[bool, str] = False,
    ) -> ExecuteThread:
        """
        Creates an ExecuteThread instance with the given parameters,
        adds it to the managed threads list, and returns it.
        """
        thread = ExecuteThread(
            python_exe=python_exe or self.python_exe,
            script_path=self.script_path,
            args=args,
            open_new_terminal=open_new_terminal,
            custom_activation_script=self.custom_activation_script,
            export_env=export_env or self.export_env,
            pre_cmd=pre_cmd,
            post_cmd=post_cmd,
        )
        self.threads.append(thread)
        return thread

    def clean_up_threads(self):
        self.threads = [t for t in self.threads if t.is_alive()]

    def terminate_all(self):
        for thread in self.threads:
            thread.terminate()
        self.threads.clear()
