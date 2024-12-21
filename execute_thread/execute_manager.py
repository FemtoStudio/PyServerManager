import os
import sys
import platform
import subprocess
import threading
import base64
import json
import signal
import logging
import psutil
import shutil
from abc import ABC, abstractmethod
from typing import Dict, Optional, Union, List, Callable

# If no logger is provided, we'll use this module-level logger.
DEFAULT_LOGGER = logging.getLogger(__name__)
DEFAULT_LOGGER.setLevel(logging.INFO)


class BaseExecutor(ABC):
    """
    Abstract base class for platform-specific execution of Python scripts.
    Each subclass must implement:
      - build_command(...)
      - run_inline(...)
      - run_in_terminal(...)
      - terminate_process(...)
    """

    OUTPUT_PREFIX = '##BEGIN_ENCODED_OUTPUT##'
    OUTPUT_SUFFIX = '##END_ENCODED_OUTPUT##'

    def __init__(
        self,
        python_exe: str,
        script_path: str,
        env_vars: Optional[Dict[str, str]] = None,
        activation_script: Optional[str] = None,
        logger: Optional[logging.Logger] = None,
    ):
        """
        :param python_exe: Path to the Python executable.
        :param script_path: Path to the Python script we want to run.
        :param env_vars: Optional dict of environment variables to set.
        :param activation_script: Path to an activation script (.bat or .sh) to source/call.
        :param logger: Custom logger or None to use default.
        """
        self.logger = logger or DEFAULT_LOGGER

        if not os.path.isfile(python_exe):
            raise FileNotFoundError(f"Python exe not found: {python_exe}")
        if not os.access(python_exe, os.X_OK):
            raise PermissionError(f"Python exe is not executable: {python_exe}")

        if not os.path.isfile(script_path):
            raise FileNotFoundError(f"Script not found: {script_path}")

        self.python_exe = python_exe
        self.script_path = script_path
        self.env_vars = env_vars or {}
        self.activation_script = activation_script

    def create_env(self) -> Dict[str, str]:
        """
        Merge os.environ + self.env_vars. Force unbuffered python output.
        """
        merged = os.environ.copy()
        merged.update(self.env_vars)
        merged["PYTHONUNBUFFERED"] = "1"
        return merged

    def base64_encode_args(self, args_dict: Dict) -> str:
        """
        Takes a dictionary of arguments, JSON-serializes it, then base64-encodes it.
        """
        serialized_args = json.dumps(args_dict)
        return base64.b64encode(serialized_args.encode("utf-8")).decode("utf-8")

    def parse_encoded_output(self, full_output: str) -> Optional[Dict]:
        """
        Look for a block: ##BEGIN_ENCODED_OUTPUT##base64##END_ENCODED_OUTPUT##
        If found, decode and return the JSON as a dict.
        """
        start_idx = full_output.find(self.OUTPUT_PREFIX)
        if start_idx == -1:
            return None
        end_idx = full_output.find(self.OUTPUT_SUFFIX, start_idx)
        if end_idx == -1:
            return None

        start_idx += len(self.OUTPUT_PREFIX)
        encoded_block = full_output[start_idx:end_idx]

        try:
            decoded_json = base64.b64decode(encoded_block).decode("utf-8")
            return json.loads(decoded_json)
        except Exception as e:
            self.logger.exception(f"Failed to decode output block: {e}")
            return None

    @abstractmethod
    def build_command(
        self,
        pre_cmd: Optional[str],
        post_cmd: Optional[str],
        args_dict: Dict
    ) -> str:
        """
        Construct the shell command to run:
          - optional activation script
          - pre_cmd
          - environment sets/exports
          - main python invocation
          - post_cmd
        Return it as a single string (for Windows or /bin/bash usage).
        """

    @abstractmethod
    def run_inline(self, final_cmd: str):
        """
        Run the final command inline (capturing stdout).
        Returns (proc, exit_code, output_string).
        """

    @abstractmethod
    def run_in_terminal(self, final_cmd: str):
        """
        Spawns a new terminal window for the final_cmd. Typically returns immediately.
        """

    @abstractmethod
    def terminate_process(self, proc) -> None:
        """
        Terminate a running process or entire process group if possible.
        """


class WindowsExecutor(BaseExecutor):
    """
    Executor for Windows.
    """

    def build_command(
        self,
        pre_cmd: Optional[str],
        post_cmd: Optional[str],
        args_dict: Dict
    ) -> str:
        """
        On Windows, chain commands with ' & '. Environment is set with 'set KEY=VALUE'.
        Also, if activation_script is provided, do: call "<activation_script>" & ...
        """
        cmd_parts = []

        # If there's an activation script, e.g. "C:\\my_env\\Scripts\\activate.bat"
        if self.activation_script:
            cmd_parts.append(f'call "{self.activation_script}"')

        if pre_cmd:
            cmd_parts.append(pre_cmd)

        for k, v in self.env_vars.items():
            cmd_parts.append(f'set {k}={v}')

        encoded_args = self.base64_encode_args(args_dict)
        main_py = f'"{self.python_exe}" "{self.script_path}" --encoded-args "{encoded_args}"'
        cmd_parts.append(main_py)

        if post_cmd:
            cmd_parts.append(post_cmd)

        final_cmd = " & ".join(cmd_parts)
        return final_cmd

    def run_inline(self, final_cmd: str):
        """
        Shell=True on Windows. Return (proc, exit_code, output).
        """
        env = self.create_env()
        self.logger.info(f"[WindowsExecutor] inline command:\n{final_cmd}\n")
        proc = subprocess.Popen(
            final_cmd,
            shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            env=env,
            universal_newlines=True
        )
        output_lines = []
        for line in proc.stdout:
            output_lines.append(line)
            self.logger.info(line.rstrip('\n'))
        proc.wait()
        exit_code = proc.returncode
        return proc, exit_code, "".join(output_lines)

    def run_in_terminal(self, final_cmd: str):
        """
        Spawns a new cmd.exe window with 'start /WAIT cmd.exe /k "..."'.
        """
        env = self.create_env()
        cmd_for_window = f'start /WAIT cmd.exe /k "{final_cmd}"'
        self.logger.info(f"[WindowsExecutor] new terminal:\n{cmd_for_window}\n")
        subprocess.Popen(
            cmd_for_window,
            shell=True,
            env=env,
            creationflags=subprocess.DETACHED_PROCESS
        )

    def terminate_process(self, proc) -> None:
        """
        Kill a Windows process and children via psutil.
        """
        if proc and proc.pid:
            try:
                parent = psutil.Process(proc.pid)
                self.logger.info(f"[WindowsExecutor] Terminating process {proc.pid}")
                for child in parent.children(recursive=True):
                    child.terminate()
                parent.terminate()
            except psutil.NoSuchProcess:
                pass


class UnixExecutor(BaseExecutor):
    """
    Executor for Linux / macOS.
    """

    def build_command(
        self,
        pre_cmd: Optional[str],
        post_cmd: Optional[str],
        args_dict: Dict
    ) -> str:
        """
        On Unix, we can chain commands with '\n'. We do 'export KEY="VALUE"'.
        If activation_script is provided, do: source "<activation_script>".
        """
        cmd_parts = []

        if self.activation_script:
            cmd_parts.append(f'source "{self.activation_script}"')

        if pre_cmd:
            cmd_parts.append(pre_cmd)

        for k, v in self.env_vars.items():
            cmd_parts.append(f'export {k}="{v}"')

        encoded_args = self.base64_encode_args(args_dict)
        main_py = f'"{self.python_exe}" "{self.script_path}" --encoded-args "{encoded_args}"'
        cmd_parts.append(main_py)

        if post_cmd:
            cmd_parts.append(post_cmd)

        # separate by newlines
        final_cmd = "\n".join(cmd_parts)
        return final_cmd

    def run_inline(self, final_cmd: str):
        """
        We'll spawn /bin/bash, pass final_cmd via stdin, capturing stdout.
        Returns (proc, exit_code, output_string).
        """
        env = self.create_env()
        self.logger.info(f"[UnixExecutor] inline command via bash:\n{final_cmd}\n")
        proc = subprocess.Popen(
            ["/bin/bash"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            env=env,
            universal_newlines=True,
            preexec_fn=os.setsid  # so we can kill child processes
        )
        # Write commands, then close stdin
        proc.stdin.write(final_cmd)
        proc.stdin.close()

        output_lines = []
        for line in proc.stdout:
            output_lines.append(line)
            self.logger.info(line.rstrip('\n'))
        proc.wait()
        exit_code = proc.returncode
        return proc, exit_code, "".join(output_lines)

    def run_in_terminal(self, final_cmd: str):
        """
        Spawns a new terminal (gnome-terminal, xterm, etc.).
        e.g. gnome-terminal -- bash -c '<final_cmd>; exec bash'
        """
        env = self.create_env()
        emulator = self._detect_terminal_emulator()
        self.logger.info(f"[UnixExecutor] new terminal: {emulator}")
        full_cmd = [
            emulator,
            "--",
            "bash",
            "-c",
            f'{final_cmd}; exec bash'
        ]
        subprocess.Popen(full_cmd, env=env)

    def terminate_process(self, proc) -> None:
        """
        Kill the entire process group via SIGTERM.
        """
        if proc and proc.pid:
            try:
                self.logger.info(f"[UnixExecutor] Terminating process group for pid {proc.pid}")
                os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
            except ProcessLookupError:
                pass

    def _detect_terminal_emulator(self) -> str:
        for emu in ["gnome-terminal", "konsole", "xterm", "mate-terminal"]:
            if shutil.which(emu):
                return emu
        raise EnvironmentError("No supported terminal emulator found on this system.")


class ExecuteThread(threading.Thread):
    """
    A thread that uses a platform-specific executor to run commands.
    Preserves a .cmd property for "silent" usage or external usage.
    Also supports inline termination if needed.
    """
    def __init__(
        self,
        executor: BaseExecutor,
        args: Dict,
        pre_cmd: Optional[str] = None,
        post_cmd: Optional[str] = None,
        open_new_terminal: bool = False,
        callback: Optional[Callable] = None,
    ):
        super().__init__()
        self.executor = executor
        self.args = args.copy()
        self.pre_cmd = pre_cmd
        self.post_cmd = post_cmd
        self.open_new_terminal = open_new_terminal
        self.callback = callback

        self.exit_code = None
        self.output = ""
        self.parsed_output = None
        self.error = None

        # We'll keep references so we can terminate if inline
        self.proc = None
        self._cmd: Optional[str] = None

        # Shortcut to logger
        self.logger = executor.logger

    @property
    def cmd(self) -> str:
        """
        Return the final command that would run on the shell.
        This is built on-demand (lazy).
        """
        if self._cmd is None:
            self._cmd = self.executor.build_command(
                pre_cmd=self.pre_cmd,
                post_cmd=self.post_cmd,
                args_dict=self.args,
            )
        return self._cmd

    def run(self):
        """
        Thread entry point: run inline or in terminal, capture output if inline, parse it, callback.
        """
        try:
            final_cmd = self.cmd  # build & store command

            if self.open_new_terminal:
                # Fire & forget
                self.executor.run_in_terminal(final_cmd)
                self.exit_code = 0  # unknown in this scenario
                self.output = ""
            else:
                # Inline - store the proc reference so we can terminate if needed
                proc, exit_code, captured = self.executor.run_inline(final_cmd)
                self.proc = proc
                self.exit_code = exit_code
                self.output = captured
                self.parsed_output = self.executor.parse_encoded_output(self.output)

        except Exception as e:
            self.logger.exception("Error running ExecuteThread")
            self.error = str(e)
        finally:
            if self.callback:
                try:
                    self.callback(self)
                except Exception as cb_exc:
                    self.logger.exception(f"Error in callback: {cb_exc}")

    def terminate(self):
        """
        Attempt to terminate the inline process if we have one.
        (Doesn't forcibly close new terminal windows.)
        """
        if self.proc and not self.open_new_terminal:
            self.executor.terminate_process(self.proc)


class ExecuteThreadManager:
    """
    Manages creation of a WindowsExecutor or UnixExecutor, spawns threads, tracks them.
    Also supports optional custom_activation_script (batch or shell).
    Provides an option to override python_exe, script_path, env, etc.
    """

    def __init__(
        self,
        python_exe: str,
        script_path: str,
        export_env: Optional[Dict[str, str]] = None,
        custom_activation_script: Optional[str] = None,
        callback: Optional[Callable] = None,
        custom_logger: Optional[logging.Logger] = None,
    ):
        """
        :param python_exe: Path to Python interpreter.
        :param script_path: Path to .py script we want to run.
        :param export_env: Extra env vars to set for the process.
        :param custom_activation_script: optional .bat or .sh to activate an environment
        :param callback: Optional global callback if you want a default for all threads.
        :param custom_logger: Optional logger. If None, a default is used.
        """
        self.callback = callback
        self.threads: List[ExecuteThread] = []

        # Decide which Executor to use
        sys_name = platform.system()
        self.logger = custom_logger or DEFAULT_LOGGER

        if sys_name == "Windows":
            self.base_executor = WindowsExecutor(
                python_exe=python_exe,
                script_path=script_path,
                env_vars=export_env,
                activation_script=custom_activation_script,
                logger=self.logger,
            )
        elif sys_name in ["Linux", "Darwin"]:
            self.base_executor = UnixExecutor(
                python_exe=python_exe,
                script_path=script_path,
                env_vars=export_env,
                activation_script=custom_activation_script,
                logger=self.logger,
            )
        else:
            raise NotImplementedError(f"No Executor available for OS: {sys_name}")

    def get_thread(
        self,
        args: Dict,
        pre_cmd: Optional[str] = None,
        post_cmd: Optional[str] = None,
        open_new_terminal: bool = False,
        callback: Optional[Callable] = None,
        # Below are optional overrides:
        python_exe: Optional[str] = None,
        script_path: Optional[str] = None,
        export_env: Optional[Dict[str, str]] = None,
        custom_activation_script: Optional[str] = None,
    ) -> ExecuteThread:
        """
        Creates a new ExecuteThread. Optionally overrides the manager-level
        python_exe, script_path, env, or activation script if you pass them here.
        """
        # If user provided overrides, create a new Executor just for this thread
        if any([python_exe, script_path, export_env, custom_activation_script]):
            # Build a new executor
            sys_name = platform.system()
            effective_py = python_exe or self.base_executor.python_exe
            effective_script = script_path or self.base_executor.script_path
            effective_env = export_env or self.base_executor.env_vars
            effective_act = custom_activation_script or self.base_executor.activation_script

            if sys_name == "Windows":
                executor = WindowsExecutor(
                    python_exe=effective_py,
                    script_path=effective_script,
                    env_vars=effective_env,
                    activation_script=effective_act,
                    logger=self.logger,
                )
            else:
                executor = UnixExecutor(
                    python_exe=effective_py,
                    script_path=effective_script,
                    env_vars=effective_env,
                    activation_script=effective_act,
                    logger=self.logger,
                )
        else:
            # reuse the base one
            executor = self.base_executor

        final_callback = callback or self.callback
        thread = ExecuteThread(
            executor=executor,
            args=args,
            pre_cmd=pre_cmd,
            post_cmd=post_cmd,
            open_new_terminal=open_new_terminal,
            callback=final_callback,
        )
        self.threads.append(thread)
        return thread

    def clean_up_threads(self):
        """
        Remove threads that have finished from the list.
        """
        self.threads = [t for t in self.threads if t.is_alive()]

    def terminate_all(self):
        """
        Terminate all threads if possible (only affects inline).
        """
        for t in self.threads:
            t.terminate()
        self.threads.clear()


def example_usage():
    # Example usage
    python_exe = sys.executable  # current python
    script_path = os.path.abspath("test_scripts/some_script.py")  # or wherever your script is

    # Create manager with or without a custom logger
    custom_logger = logging.getLogger("MyCustomLogger")
    custom_logger.setLevel(logging.DEBUG)
    handler = logging.StreamHandler(sys.stdout)
    custom_logger.addHandler(handler)

    manager = ExecuteThreadManager(
        python_exe=python_exe,
        script_path=script_path,
        export_env={"FOO": "BAR"},
        custom_activation_script=None,  # e.g. "C:/path/to/activate.bat" or "/home/user/activate.sh"
        callback=lambda thr: print(f"[Global callback] error? {thr.error}, output:\n{thr.output}"),
        custom_logger=custom_logger,
    )

    args_dict = {"some_key": 123, "another": "hello world"}

    # 1) "Silent" usage (i.e., get the command without starting the thread)
    t_silent = manager.get_thread(args=args_dict, pre_cmd="echo PreCmd", post_cmd="echo PostCmd")
    built_cmd = t_silent.cmd
    print("SILENT CMD:\n", built_cmd)

    # Actually run inline
    t_silent.start()
    t_silent.join()
    print("Silent run output:\n", t_silent.output)
    print("Parsed output:\n", t_silent.parsed_output)

    # 2) Another example: new terminal (fire & forget)
    t_terminal = manager.get_thread(args=args_dict, open_new_terminal=True)
    print("Terminal command:\n", t_terminal.cmd)
    t_terminal.start()
    t_terminal.join()
    print("Finished new-terminal thread.")

    # 3) Overriding python_exe on a single thread
    alt_py = sys.executable  # maybe a different interpreter
    alt_thread = manager.get_thread(
        args=args_dict,
        python_exe=alt_py,
        pre_cmd="echo Using alt py!",
    )
    # This will create a new WindowsExecutor or UnixExecutor object with the overridden python_exe
    alt_thread.start()
    alt_thread.join()

    # Terminate all (inline) threads if needed
    manager.terminate_all()
    manager.clean_up_threads()


if __name__ == "__main__":
    example_usage()
