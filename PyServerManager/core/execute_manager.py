import base64
import logging
import os
import platform
import shutil
import signal
import subprocess
import sys
import threading
from abc import ABC, abstractmethod
from typing import Optional, List, Callable

import psutil

# Default logger if none is provided
DEFAULT_LOGGER = logging.getLogger(__name__)
DEFAULT_LOGGER.setLevel(logging.INFO)

import json
from typing import Any, Dict


def _dict_to_cli_args(args_dict: Dict[str, Any]) -> str:
    """
    Converts a dict of {key: value} into a string of CLI args like:
      --key1 "value1" --key2 "value2"

    1) If the value is a dict or list, we JSON-serialize it (recursively).
    2) If it already is a string/number/bool/None, we convert it to a string directly.
    3) We then escape any double quotes to avoid shell parsing issues.
    4) Finally, we build a single string of arguments in the form:
         --key "serialized_value"
       separated by spaces.

    Example:
      args_dict = {
          "name": "My Item",
          "params": {"threshold": 0.75, "layers": [1, 2, 3]},
          "debug": True
      }
      result -> '--name "My Item" --params "{\\"threshold\\": 0.75, \\"layers\\": [1, 2, 3]}" --debug "True"'
    """
    parts = []
    for k, v in args_dict.items():
        # If the value is a dict or list, let's JSON-serialize it
        if isinstance(v, (dict, list)):
            serialized = json.dumps(v)
        else:
            # Convert scalars or None to string
            serialized = str(v)

        # Escape any double quotes inside the serialized string
        escaped = serialized.replace('"', '\\"')

        # Build the final argument piece
        parts.append(f'--{k} "{escaped}"')

    return " ".join(parts)


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

    def stream_output_lines(self, stream):
        """
        Utility to read lines from a stream until EOF, logging them as we go.
        """
        output_lines = []
        while True:
            line = stream.readline()
            if not line:
                break
            self.logger.info(line.rstrip('\n'))
            output_lines.append(line)
        return output_lines

    @abstractmethod
    def build_command(
            self,
            pre_cmd: Optional[str],
            post_cmd: Optional[str],
            args_dict: Dict,
            encode_args: bool = True
    ) -> str:
        """
        Construct the final shell command string, e.g.:
          1) optional activation script
          2) pre_cmd
          3) environment sets/exports
          4) the main python call (either --encoded-args or normal CLI)
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


class WindowsExecutor(BaseExecutor):
    """
    Executor for Windows.
    """

    def build_command(
            self,
            pre_cmd: Optional[str],
            post_cmd: Optional[str],
            args_dict: Dict,
            encode_args: bool = True
    ) -> str:
        """
        On Windows, chain with ' & '. Use 'call "<script>.bat"' if activation_script is set.
        Also 'set KEY=VAL' for environment variables.
        If encode_args=True, we do --encoded-args. Else we do normal CLI arguments.
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

        if encode_args:
            # base64 approach
            encoded_str = self.base64_encode_args(args_dict)
            main_py = f'"{self.python_exe}" "{self.script_path}" --encoded-args "{encoded_str}"'
        else:
            # normal args
            arg_string = _dict_to_cli_args(args_dict)
            main_py = f'"{self.python_exe}" "{self.script_path}" {arg_string}'

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

        # Just for logging, redacting base64
        log_cmd = final_cmd
        if "--encoded-args" in log_cmd:
            # Redact after the = sign for cleanliness
            # or just do a simple approach:
            log_cmd = log_cmd.rsplit('--encoded-args', 1)[0] + '--encoded-args ...'
            self.logger.debug(f"[WindowsExecutor] redacted command:\n{log_cmd}\n")

        self.logger.info(f"[WindowsExecutor] inline command:\n{log_cmd}\n")

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

        # if the proc got terminated, self.proc would be set to None
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

        log_cmd = cmd_for_window
        if "--encoded-args" in log_cmd:
            log_cmd = log_cmd.rsplit('--encoded-args', 1)[0] + '--encoded-args ...'

        self.logger.info(f"[WindowsExecutor] new terminal:\n{log_cmd}\n")

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

    def build_command(
            self,
            pre_cmd: Optional[str],
            post_cmd: Optional[str],
            args_dict: Dict,
            encode_args: bool = True
    ) -> str:
        """
        On Unix, we can chain lines with '\n'. Use 'source "<script>.sh"' if activation_script is set.
        Also 'export KEY="VAL"' for environment variables.
        If encode_args=True, we do --encoded-args. Else we do normal CLI arguments.
        """
        lines = []

        if self.activation_script:
            lines.append(f'source "{self.activation_script}"')

        if pre_cmd:
            lines.append(pre_cmd)

        for k, v in self.env_vars.items():
            lines.append(f'export {k}="{v}"')

        if encode_args:
            # base64 approach
            encoded_str = self.base64_encode_args(args_dict)
            main_py = f'"{self.python_exe}" "{self.script_path}" --encoded-args "{encoded_str}"'
        else:
            # normal args
            arg_string = _dict_to_cli_args(args_dict)
            main_py = f'"{self.python_exe}" "{self.script_path}" {arg_string}'

        lines.append(main_py)

        if post_cmd:
            lines.append(post_cmd)

        return "\n".join(lines)

    def run_inline(self, final_cmd: str):
        env = self.create_env()

        # Just for logging, redacting base64
        log_cmd = final_cmd
        if "--encoded-args" in log_cmd:
            log_cmd = log_cmd.rsplit('--encoded-args', 1)[0] + '--encoded-args ...'
        self.logger.info(f"[UnixExecutor] inline:\n{log_cmd}\n")

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

        # if the proc got terminated, self.proc would be set to None
        if self.proc is None:
            return None, None, ""

        self.proc.wait()
        exit_code = self.proc.returncode
        return self.proc, exit_code, "".join(output_lines)

    def run_in_terminal(self, final_cmd: str):
        env = self.create_env()
        emulator = self._detect_terminal_emulator()

        log_cmd = final_cmd
        if "--encoded-args" in log_cmd:
            log_cmd = log_cmd.rsplit('--encoded-args', 1)[0] + '--encoded-args ...'
        self.logger.info(f"[UnixExecutor] new terminal: {emulator}\nCmd:\n{log_cmd}")

        full_cmd = [emulator, "--", "bash", "-c", f'{final_cmd}; exec bash']
        subprocess.Popen(full_cmd, env=env)

    def terminate_process(self, proc: subprocess.Popen) -> None:
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
            callback: Optional[Callable] = None,
            encode_args: bool = True
    ):
        super().__init__()
        self.executor = executor
        self.args = args.copy()
        self.pre_cmd = pre_cmd
        self.post_cmd = post_cmd
        self.open_new_terminal = open_new_terminal
        self.callback = callback

        self.encode_args = encode_args  # NEW: if False => pass normal CLI args

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
                args_dict=self.args,
                encode_args=self.encode_args
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
                # If we used encode_args=True, parse for embedded JSON
                if self.encode_args:
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
        self.executor.terminate_process(self.proc)

    def __str__(self):
        return f"<ExecuteThread {self.name} exit_code={self.exit_code} output={self.output}>"

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
            encode_args: bool = True,
            # optional overrides
            python_exe: Optional[str] = None,
            script_path: Optional[str] = None,
            export_env: Optional[Dict[str, str]] = None,
            custom_activation_script: Optional[str] = None,
    ) -> ExecuteThread:
        """
        Creates a new ExecuteThread. Optionally overrides python_exe/script_path/export_env/etc.
        If encode_args=False, we won't do base64 encoding, but pass normal CLI args.
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
            callback=final_callback,
            encode_args=encode_args
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

    # 1) Example using encode_args=True (the default)
    t_encoded = manager.get_thread(
        args={"myArg": 123, "anotherKey": "hello"},
        pre_cmd="echo PRE_CMD",
        post_cmd="echo POST_CMD",
        open_new_terminal=False,
        encode_args=True
    )
    print("Encoded CMD:\n", t_encoded.cmd)
    t_encoded.start()
    t_encoded.join()
    print("Output:\n", t_encoded.output)
    print("Parsed Output (since encode_args=True):\n", t_encoded.parsed_output)

    # 2) Example using encode_args=False => pass as normal CLI arguments
    t_normal = manager.get_thread(
        args={"myArg": 999, "foo": "bar with spaces"},
        open_new_terminal=True,
        encode_args=False
    )
    print("Normal Args CMD:\n", t_normal.cmd)
    t_normal.start()
    t_normal.join()
    print("Output:\n", t_normal.output)
    print("Parsed Output (encode_args=False => None):\n", t_normal.parsed_output)

    # Clean up done threads
    manager.clean_up_threads()


if __name__ == "__main__":
    example_usage()
