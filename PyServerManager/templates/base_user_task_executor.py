import logging
import sys
from pathlib import Path

from PyServerManager.core.execute_manager import ExecuteThreadManager
from PyServerManager.core.logger import SingletonLogger


class BaseUserTaskExecutor:
    """
    Base template class for user-defined tools that run via the 'task_executor' pattern.

    Responsibilities / Usage:
      1. Holds an ExecuteThreadManager, which can run Python scripts in
         inline or new-terminal mode.
      2. Provides a logger instance.
      3. Has a class-level `EXECUTOR_SCRIPT_PATH` that the user or subclass can override.
      4. Exposes a `gather_args()` method so that child classes can build up
         the command-line args for each run.
      5. Has an `execute(...)` method that actually spawns a new thread (using
         the manager) to run the script.
    """

    # Dynamically compute the path to executors/task_executor.py
    EXECUTOR_SCRIPT_PATH = str(
        (Path(__file__).parent.parent / "executors" / "task_executor.py").resolve()
    )

    def __init__(
            self,
            python_exe: str = None,
            activation_script: str = None,
            env_vars: dict = None,
            logger: logging.Logger = None
    ):
        """
        :param python_exe: Path to Python interpreter if you want a specific env
        :param activation_script: Path to an activate script (.sh/.bat) if needed
        :param env_vars: Extra environment variables
        :param logger: Optional logger; if None, we get a default singleton logger
        """
        # Logger
        self.logger = logger or SingletonLogger.get_instance("BaseUserTaskExecutor")

        # Choose python_exe or default to the current interpreter
        if python_exe is None:
            python_exe = sys.executable

        self.python_exe = python_exe
        self.activation_script = activation_script
        self.env_vars = env_vars or {}

        # Create an ExecuteThreadManager using the script path
        self.executor_manager = ExecuteThreadManager(
            python_exe=self.python_exe,
            script_path=self.EXECUTOR_SCRIPT_PATH,
            export_env=self.env_vars,
            custom_activation_script=self.activation_script,
            callback=self._global_callback,  # will be invoked after each thread finishes
            custom_logger=self.logger
        )

    def gather_args(self, **kwargs):
        """
        Intended for child classes or the user to override or extend.
        Build up a dictionary of CLI arguments or config.
        """
        base_args = {}
        base_args.update(kwargs)
        return base_args

    def execute(
            self,
            args_dict: dict = None,
            pre_cmd: str = None,
            post_cmd: str = None,
            open_new_terminal: bool = False,
            encode_args: bool = True,
            callback=None
    ):
        """
        Spawns a new ExecuteThread for the given arguments.

        :param args_dict: Dict of arguments (will be base64-encoded if encode_args=True)
        :param pre_cmd: Optional shell command to run before the Python script
        :param post_cmd: Optional shell command to run after the Python script
        :param open_new_terminal: If True, spawns a new terminal window (no output captured)
        :param encode_args: If True, pass arguments via --encoded-args
        :param callback: If provided, override the global callback for this thread only
        :return: The ExecuteThread object
        """
        final_args = args_dict or {}
        print("final_args", final_args)
        # Make the thread
        thread = self.executor_manager.get_thread(
            args=final_args,
            pre_cmd=pre_cmd,
            post_cmd=post_cmd,
            open_new_terminal=open_new_terminal,
            encode_args=encode_args,
            callback=callback  # per-thread callback if needed
        )

        # Start thread (non-blocking)
        thread.start()
        return thread

    def _global_callback(self, thread):
        """
        A default global callback triggered after each ExecuteThread completes.
        Logs the exit code, error, and any captured output.
        """
        self.logger.info(f"[Global Callback] Thread finished: exit_code={thread.exit_code}, error={thread.error}")
        if thread.output:
            self.logger.info(f"Output:\n{thread.output}")
        if thread.parsed_output:
            self.logger.info(f"Parsed JSON Output:\n{thread.parsed_output}")


if __name__ == "__main__":
    """
    Quick test to confirm that BaseUserTaskExecutor can spawn the task_executor.
    We'll pass some sample arguments and wait for the script to finish.
    """
    print("Running BaseUserTaskExecutor as a standalone test...")

    # 1) Create an instance of BaseUserTaskExecutor
    executor = BaseUserTaskExecutor()

    # 2) Build some example arguments to pass to task_executor.py.
    #    If your task_executor.py expects normal CLI flags, you might do encode_args=False.
    #    If it expects --encoded-args, you can keep encode_args=True. Adjust as needed.
    example_args = {"myArg": "HelloWorld", "number": 42}

    # 3) Execute it, capturing the returned thread.
    #    We'll do encode_args=False so that myArg => --myArg "HelloWorld"
    #    (If your task_executor expects base64, you can flip this to True)
    thread = executor.execute(args_dict=example_args, encode_args=True, open_new_terminal=True)

    # 4) Wait for the task script to complete
    thread.join()

    print("Test run complete. Check logs above for details.")
