import base64
import json
import logging
import os
import platform
import shutil
import signal
import subprocess
import sys
import threading
from abc import ABC, abstractmethod
from typing import Dict, Optional, List, Callable

import psutil

# Default logger if none is provided
DEFAULT_LOGGER = logging.getLogger(__name__)
DEFAULT_LOGGER.setLevel(logging.INFO)


class BaseExecutor(ABC):
    """
    Abstract base class for platform-specific execution of Python scripts.
    Each subclass implements build_command, run_inline, run_in_terminal, and terminate_process.
    """

    OUTPUT_PREFIX = '##BEGIN_ENCODED_OUTPUT##'
    OUTPUT_SUFFIX = '##END_ENCODED_OUTPUT##'

    def __init__(
            self,
            python_exe: str,
            script_path: str,
            env_vars: Optional[Dict[str, str]] = None,
            activation_script: Optional[str] = None,
            logger: Optional[logging.Logger] = None
    ):
        """
        :param python_exe: Path to the Python interpreter.
        :param script_path: Path to the target .py script.
        :param env_vars: Extra environment variables to set before running.
        :param activation_script: Optional .bat/.sh to activate an environment.
        :param logger: Optional custom logger; if None, uses default.
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
        self.proc: Optional[subprocess.Popen] = None

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
        Convert dictionary -> JSON -> base64-encoded string
        for --encoded-args usage.
        """
        serialized_args = json.dumps(args_dict)
        return base64.b64encode(serialized_args.encode("utf-8")).decode("utf-8")

    def parse_encoded_output(self, full_output: str) -> Optional[Dict]:
        """
        Looks for a block:
            ##BEGIN_ENCODED_OUTPUT##<base64>##END_ENCODED_OUTPUT##
        Returns the parsed dictionary, or None if not found.
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
    def build_command(self, pre_cmd: Optional[str], post_cmd: Optional[str], args_dict: Dict) -> str:
        """
        Construct the final shell command string, e.g.:
          1) optional activation script
          2) pre_cmd
          3) environment sets/exports
          4) the main python call with --encoded-args
          5) post_cmd
        """

    @abstractmethod
    def run_inline(self, final_cmd: str) -> "tuple[subprocess.Popen, int, str]":
        """
        Execute inline (capture output line-by-line), but do NOT wait for the process
        prior to returning—so we can terminate mid-run. Instead, read lines in a loop,
        store them, then call proc.wait() after the loop ends.

        Returns (proc, exit_code, combined_output).
        """

    @abstractmethod
    def run_in_terminal(self, final_cmd: str) -> None:
        """
        Fire-and-forget in a new terminal window. No output capturing.
        """

    @abstractmethod
    def terminate_process(self, proc: subprocess.Popen) -> None:
        """
        OS-specific logic to kill a running process and its children.
        """

    def stream_output_lines(self, stream):
        output_lines = []
        while True:
            line = stream.readline()
            if not line:
                break
            self.logger.info(line.rstrip('\n'))
            output_lines.append(line)
        return output_lines


class WindowsExecutor(BaseExecutor):
    """
    Executor for Windows.
    """

    def build_command(self, pre_cmd: Optional[str], post_cmd: Optional[str], args_dict: Dict) -> str:
        """
        On Windows, chain with ' & '.  Use 'call "<script>.bat"' if activation_script is set.
        Also 'set KEY=VAL' for environment variables.
        """
        lines = []

        # Activation script?
        if self.activation_script:
            lines.append(f'call "{self.activation_script}"')

        # Pre-cmd
        if pre_cmd:
            lines.append(pre_cmd)

        # Env vars
        for k, v in self.env_vars.items():
            lines.append(f'set {k}={v}')

        # Main python call
        encoded_args = self.base64_encode_args(args_dict)
        main_py = f'"{self.python_exe}" "{self.script_path}" --encoded-args "{encoded_args}"'
        lines.append(main_py)

        # Post-cmd
        if post_cmd:
            lines.append(post_cmd)

        # Windows likes chaining with &
        return " & ".join(lines)

    def run_inline(self, final_cmd: str):
        """
        Use shell=True, line-by-line reading from stdout.
        We'll only do proc.wait() after reading lines, so we can kill early if needed.
        """
        env = self.create_env()
        cmd_print = final_cmd.rsplit('-encoded-args', 1)[0] + '-encoded-args ...'
        self.logger.info(f"[WindowsExecutor] inline command:\n{cmd_print}\n")

        proc = subprocess.Popen(
            final_cmd,
            shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            env=env,
            universal_newlines=True
        )
        self.proc = proc  # store so we can terminate

        output_lines = self.stream_output_lines(self.proc.stdout)

        # if the proc got terminated nothing to wait for
        if self.proc is None:
            return None, None, ""
        # Only after no more lines do we .wait() for final returncode
        self.proc.wait()
        exit_code = self.proc.returncode
        return self.proc, exit_code, "".join(output_lines)

    def run_in_terminal(self, final_cmd: str):
        """
        Spawns a new cmd.exe window.
        e.g. start /WAIT cmd.exe /k "..."
        """
        env = self.create_env()
        cmd_for_window = f'start /WAIT cmd.exe /k "{final_cmd}"'
        cmd_print = final_cmd.rsplit('-encoded-args', 1)[0] + '-encoded-args ...'
        self.logger.info(f"[WindowsExecutor] new terminal:\n{cmd_print}\n")
        subprocess.Popen(
            cmd_for_window,
            shell=True,
            env=env,
            creationflags=subprocess.DETACHED_PROCESS
        )

    def terminate_process(self, proc: subprocess.Popen) -> None:
        """
        Kill the process and children via psutil, if it still exists.
        """
        if not self.proc or self.proc.poll() is not None:
            # Already gone, do nothing
            return

        try:
            parent = psutil.Process(self.proc.pid)
            self.logger.info(f"[WindowsExecutor] terminating PID={self.proc.pid}")
            for child in parent.children(recursive=True):
                child.terminate()
            parent.terminate()
            self.proc = None
        except psutil.NoSuchProcess:
            pass


class UnixExecutor(BaseExecutor):
    """
    Executor for Linux / macOS.
    """

    def build_command(self, pre_cmd: Optional[str], post_cmd: Optional[str], args_dict: Dict) -> str:
        """
        On Unix, we can chain lines with '\n'. Use 'source "<script>.sh"' if activation_script is set.
        Also 'export KEY="VAL"' for environment variables.
        """
        lines = []

        if self.activation_script:
            lines.append(f'source "{self.activation_script}"')

        if pre_cmd:
            lines.append(pre_cmd)

        for k, v in self.env_vars.items():
            lines.append(f'export {k}="{v}"')

        encoded_args = self.base64_encode_args(args_dict)
        main_py = f'"{self.python_exe}" "{self.script_path}" --encoded-args "{encoded_args}"'
        lines.append(main_py)

        if post_cmd:
            lines.append(post_cmd)

        return "\n".join(lines)

    def run_inline(self, final_cmd: str):
        """
        Start /bin/bash, do line-by-line reading from stdout,
        store proc in case we want to kill it mid-run. Wait after reading lines.
        """
        env = self.create_env()
        cmd_print = final_cmd.rsplit('-encoded-args', 1)[0] + '-encoded-args ...'
        self.logger.info(f"[UnixExecutor] inline:\n{cmd_print}\n")

        proc = subprocess.Popen(
            ["/bin/bash"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            env=env,
            universal_newlines=True,
            preexec_fn=os.setsid  # so we can kill the entire process group
        )
        self.proc = proc
        # We write final_cmd, then read lines until EOF
        self.proc.stdin.write(final_cmd + "\n")
        self.proc.stdin.close()

        output_lines = self.stream_output_lines(self.proc.stdout)

        # if the proc got terminated nothing to wait for
        if self.proc is None:
            return None, None, ""

        # Now wait for the child process to fully exit
        self.proc.wait()
        exit_code = self.proc.returncode
        return self.proc, exit_code, "".join(output_lines)

    def run_in_terminal(self, final_cmd: str):
        """
        e.g. gnome-terminal -- bash -c '<final_cmd>; exec bash'
        """
        env = self.create_env()
        emulator = self._detect_terminal_emulator()
        self.logger.info(f"[UnixExecutor] new terminal: {emulator}")
        cmd_print = final_cmd.rsplit('-encoded-args', 1)[0] + '-encoded-args ...'
        full_cmd = [emulator, "--", "bash", "-c", f'{cmd_print}; exec bash']
        subprocess.Popen(full_cmd, env=env)

    def terminate_process(self, proc: subprocess.Popen) -> None:
        """
        Kill the process group (pgid) with SIGTERM.
        """
        if self.proc and self.proc.pid:
            pgid = os.getpgid(self.proc.pid)
            self.logger.info(f"[UnixExecutor] terminating PGID={pgid} for PID={self.proc.pid}")
            try:
                os.killpg(pgid, signal.SIGTERM)
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
    Has a .cmd property for silent usage or passing to external runner.
    In inline mode, can be terminated via .terminate().
    """

    def __init__(
            self,
            executor: BaseExecutor,
            args: Dict,
            pre_cmd: Optional[str] = None,
            post_cmd: Optional[str] = None,
            open_new_terminal: bool = False,
            callback: Optional[Callable] = None
    ):
        super().__init__()
        self.executor = executor
        self.args = args.copy()
        self.pre_cmd = pre_cmd
        self.post_cmd = post_cmd
        self.open_new_terminal = open_new_terminal
        self.callback = callback

        self.exit_code: Optional[int] = None
        self.output: str = ""
        self.parsed_output: Optional[Dict] = None
        self.error: Optional[str] = None

        self.proc: Optional[subprocess.Popen] = None
        self._cmd: Optional[str] = None

        self.logger = self.executor.logger

    @property
    def cmd(self) -> str:
        """
        The final shell command to run. Built lazily.
        """
        if self._cmd is None:
            self._cmd = self.executor.build_command(
                pre_cmd=self.pre_cmd,
                post_cmd=self.post_cmd,
                args_dict=self.args
            )
        return self._cmd

    def run(self):
        """
        Thread entry point. Runs inline or new-terminal. Captures output if inline.
        """
        try:
            final_cmd = self.cmd  # build command string

            if self.open_new_terminal:
                self.executor.run_in_terminal(final_cmd)
                self.exit_code = 0  # unknown
                self.output = ""
            else:
                # inline
                proc, exit_code, captured = self.executor.run_inline(final_cmd)
                self.proc = proc
                self.exit_code = exit_code
                self.output = captured
                self.parsed_output = self.executor.parse_encoded_output(self.output)

        except Exception as e:
            self.logger.exception("Error in ExecuteThread.run()")
            self.error = str(e)
        finally:
            # Fire callback if present
            if self.callback:
                try:
                    self.callback(self)
                except Exception as cb_exc:
                    self.logger.exception(f"Error in callback: {cb_exc}")

    def terminate(self):
        """
        If inline, kill the process group or parent+children.
        If new_terminal, we don't store a handle, so we can't forcibly close it from here.
        """
        # if self.proc and not self.open_new_terminal:
        self.executor.terminate_process(self.proc)


class ExecuteThreadManager:
    """
    Manages creation of a WindowsExecutor or UnixExecutor, spawns threads, tracks them.
    Supports optional custom_activation_script, overriding python_exe/script_path/export_env
    per-thread, and terminates inline threads on request.
    """

    def __init__(
            self,
            python_exe: str,
            script_path: str,
            export_env: Optional[Dict[str, str]] = None,
            custom_activation_script: Optional[str] = None,
            callback: Optional[Callable] = None,
            custom_logger: Optional[logging.Logger] = None
    ):
        self.callback = callback
        self.threads: List[ExecuteThread] = []

        self.logger = custom_logger or DEFAULT_LOGGER

        sys_name = platform.system()
        if sys_name == "Windows":
            self.base_executor = WindowsExecutor(
                python_exe=python_exe,
                script_path=script_path,
                env_vars=export_env,
                activation_script=custom_activation_script,
                logger=self.logger
            )
        elif sys_name in ["Linux", "Darwin"]:
            self.base_executor = UnixExecutor(
                python_exe=python_exe,
                script_path=script_path,
                env_vars=export_env,
                activation_script=custom_activation_script,
                logger=self.logger
            )
        else:
            raise NotImplementedError(f"No Executor for OS: {sys_name}")

    def get_thread(
            self,
            args: Dict,
            pre_cmd: Optional[str] = None,
            post_cmd: Optional[str] = None,
            open_new_terminal: bool = False,
            callback: Optional[Callable] = None,
            # optional overrides
            python_exe: Optional[str] = None,
            script_path: Optional[str] = None,
            export_env: Optional[Dict[str, str]] = None,
            custom_activation_script: Optional[str] = None,
    ) -> ExecuteThread:
        """
        Creates a new ExecuteThread. Optionally overrides python_exe/script_path/export_env/etc.
        """
        # If user provided overrides, build a fresh Executor just for this thread
        if any([python_exe, script_path, export_env, custom_activation_script]):
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
                    logger=self.logger
                )
            else:
                executor = UnixExecutor(
                    python_exe=effective_py,
                    script_path=effective_script,
                    env_vars=effective_env,
                    activation_script=effective_act,
                    logger=self.logger
                )
        else:
            executor = self.base_executor

        final_callback = callback or self.callback

        thread = ExecuteThread(
            executor=executor,
            args=args,
            pre_cmd=pre_cmd,
            post_cmd=post_cmd,
            open_new_terminal=open_new_terminal,
            callback=final_callback
        )
        self.threads.append(thread)
        return thread

    def clean_up_threads(self):
        """
        Remove finished threads from self.threads.
        """
        self.threads = [t for t in self.threads if t.is_alive()]

    def terminate_all(self):
        """
        Terminate all inline threads. (Doesn't forcibly close new-terminal windows.)
        """
        for t in self.threads:
            t.terminate()
        self.threads.clear()


def example_usage():
    """
    Example usage: Create manager, get threads, run them, etc.
    """
    import logging

    # Let's set up a console logger
    console_logger = logging.getLogger("MyCustomLogger")
    console_logger.setLevel(logging.DEBUG)
    handler = logging.StreamHandler(sys.stdout)
    console_logger.addHandler(handler)

    python_exe = sys.executable
    script_path = os.path.abspath("test_scripts/some_script.py")  # or wherever your script is

    manager = ExecuteThreadManager(
        python_exe=python_exe,
        script_path=script_path,
        export_env={"SOME_VAR": "SOME_VAL"},
        custom_activation_script=None,  # e.g. "/home/user/env/bin/activate.sh" or "C:/path/activate.bat"
        callback=lambda thr: print(f"[GlobalCB] Thread done, exit_code={thr.exit_code}, error={thr.error}"),
        custom_logger=console_logger
    )

    # We'll build a thread that runs inline
    t_inline = manager.get_thread(
        args={"myArg": 123},
        pre_cmd="echo PRE_CMD",
        post_cmd="echo POST_CMD",
        open_new_terminal=False
    )

    # We can see the final shell command
    print("Inline CMD:\n", t_inline.cmd)

    # Start it
    t_inline.start()

    # Optionally, you could terminate mid-run:
    # manager.terminate_all()

    # Wait for it to finish
    t_inline.join()
    print("Thread Output:", t_inline.output)
    print("Parsed Output:", t_inline.parsed_output)

    # Clean up done threads
    manager.clean_up_threads()

    # Example new terminal usage
    t_term = manager.get_thread(args={"msg": "hello from new terminal"}, open_new_terminal=True)
    print("Terminal CMD:\n", t_term.cmd)
    t_term.start()
    t_term.join()


if __name__ == "__main__":
    example_usage()
