# base_user_server_executor.py
import asyncio
import logging
import socket
import threading
import time
import traceback
from pathlib import Path

from PyServerManager.async_server.async_pickle_client import AsyncPickleClient
from PyServerManager.core.logger import SingletonLogger
from PyServerManager.templates.base_user_task_executor import BaseUserTaskExecutor


class BaseUserServerExecutor(BaseUserTaskExecutor):
    """
    Spawns the AsyncPickleServer in a separate Python process
    (via acync_server_executor.py) and manages a single event loop
    in *this* process to run its AsyncPickleClient calls without
    collisions.
    """

    EXECUTOR_SCRIPT_PATH = str(
        (Path(__file__).parent.parent / "executors" / "acync_server_executor.py").resolve()
    )

    def __init__(
            self,
            python_exe: str = None,
            activation_script: str = None,
            env_vars: dict = None,
            logger: logging.Logger = None
    ):
        super().__init__(
            python_exe=python_exe,
            activation_script=activation_script,
            env_vars=env_vars,
            logger=logger or SingletonLogger.get_instance("BaseUserServerExecutor"),
        )
        self.client: AsyncPickleClient = None
        self.host = None
        self.port = None

        # We maintain a single event loop to reuse across connect/send/shutdown
        self._loop = None

    @property
    def loop(self):
        """
        Ensure we have a single dedicated event loop for this executor.
        Then set it as the current event loop on each call so that
        StreamReader/Writer remain valid.
        """
        if self._loop is None:
            self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        return self._loop

    def _check_server_reachable(self, host, port, timeout=1.0) -> bool:
        """
        Returns True if something is listening on (host, port).
        We do a simple socket connect test.
        """
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(timeout)
        try:
            s.connect((host, port))
            s.close()
            return True
        except (ConnectionRefusedError, socket.timeout, OSError):
            return False

    def run_server(self, host="localhost", port=5050, open_new_terminal=False, **kwargs):
        """
        Launch the AsyncPickleServer in a separate process (unless we detect
        a server is already running on that port).
        """
        self.host = host
        self.port = port

        # (A) Check if our own server object is alive
        if getattr(self, "server_thread", None) and self.server_thread.is_alive():
            if self.client and self.client.is_connected:
                self.logger.warning("Server is already running; client is connected. Doing nothing.")
                return
            else:
                self.logger.warning("Server seems to be running, but client not connected. Connecting now...")
                self.connect_client()
                return

        # (B) Or check externally if some process is already bound
        if self._check_server_reachable(host, port):
            self.logger.warning(
                f"Detected an existing process on {host}:{port}. "
                f"Will attempt to connect as a client rather than starting a new server."
            )
            self.connect_client()
            return

        self.logger.info(f"Starting server on {host}:{port}...")
        args_dict = {
            "host": self.host,
            "port": self.port,
            "open_in_new_terminal": open_new_terminal,
            # ...
        }
        args_dict.update(kwargs)
        # Fire up a new process (or thread) via self.execute(...)
        self.logger.info(f"Starting server in a new process...{args_dict}")
        self.server_thread = self.execute(
            args_dict=args_dict,
            encode_args=True,
            open_new_terminal=open_new_terminal
        )
        return self.server_thread

    #
    # def run_server(self, host="localhost", port=5050, open_new_terminal=False):
    #     """
    #     Launch the AsyncPickleServer in a separate Python interpreter
    #     using the ExecutorThreadManager. That separate process will block
    #     inside its own asyncio loop until we shut it down.
    #     """
    #     self.host = host
    #     self.port = port
    #     self.logger.info(f"Starting server on {host}:{port}...")
    #
    #     args_dict = {
    #         "host": self.host,
    #         "port": self.port,
    #     }
    #
    #     # Fire up a new process
    #     thread = self.execute(
    #         args_dict=args_dict,
    #         encode_args=True,
    #         open_new_terminal=open_new_terminal
    #     )
    #     return thread

    def connect_client(self, start_sleep=2, retry_delay=2, max_retries=None):

        # self._connect_client(
        #     start_sleep=start_sleep,
        #     retry_delay=retry_delay,
        #     max_retries=max_retries)
        if self.host is None:
            self.logger.error("No host specified for client connection.")
            return
        if self.port is None:
            self.logger.error("No port specified for client connection.")
            return
        self.client = AsyncPickleClient(host=self.host, port=self.port, logger=self.logger)

        threading.Thread(target=self._connect_client, daemon=True, args=(start_sleep, retry_delay, max_retries)).start()

    def _connect_client(self, start_sleep=2, retry_delay=2, max_retries=None):
        """
        Synchronously create an AsyncPickleClient and attempt to connect
        to the server in the *same* event loop as any subsequent calls.
        """
        if self.client is not None and self.client.is_connected:
            self.logger.info("Client is already connected.")
            return

        self.logger.info("Creating AsyncPickleClient and attempting connection...")

        async def _connect_flow():
            await self.client.background_retry_connect(
                start_sleep=start_sleep,
                retry_delay=retry_delay,
                max_retries=max_retries
            )
            if self.client.is_connected:
                self.logger.info("Client connected successfully!")
            else:
                self.logger.warning("Client could not connect (timed out or user stopped).")

        self.loop.run_until_complete(_connect_flow())

    def send_data_to_server(self, data):
        """
        Synchronously send data (a dictionary, etc.) to the server
        and get its response. Uses the same event loop as connect/shutdown.
        """
        if not self.client or not self.client.is_connected:
            self.logger.warning("No connected client to send data. Call connect_client first.")
            return None

        async def _send_data_flow():
            return await self.client.send_data(data)

        try:
            return self.loop.run_until_complete(_send_data_flow())
        except TimeoutError as te:
            self.logger.error(f"Timeout waiting for connection: {te}")
            self.logger.error(f"Traceback: {traceback.format_exc()}")
            return None
        except Exception as e:
            self.logger.error(f"Error in send_data_to_server: {e}")
            self.logger.error(f"Traceback: {traceback.format_exc()}")
            return None

    def get_server_info(self):

        if not self.client or not self.client.is_connected:
            self.logger.warning("No connected client to send data. Call connect_client first.")
            return None

        async def _send_cmd_flow():
            return await self.client.send_cmd("get_server_info")

        try:
            return self.loop.run_until_complete(_send_cmd_flow())
        except TimeoutError as te:
            self.logger.error(f"Timeout waiting for connection: {te}")
            self.logger.error(f"Traceback: {traceback.format_exc()}")
            return None
        except Exception as e:
            self.logger.error(f"Error in send_data_to_server: {e}")
            self.logger.error(f"Traceback: {traceback.format_exc()}")
            return None

    def shutdown_server(self):
        """
        Synchronously send the 'shutdown_server' command to the remote server process.
        """
        if not self.client or not self.client.is_connected:
            self.logger.warning("No connected client, cannot send shutdown.")
            return None

        async def _shutdown_flow():
            return await self.client.shutdown_server()

        try:
            resp = self.loop.run_until_complete(_shutdown_flow())
            self.logger.info(f"Server shutdown response: {resp}")
            return resp
        except TimeoutError as te:
            self.logger.error(f"Timeout waiting to send shutdown: {te}")
            self.logger.error(f"Traceback: {traceback.format_exc()}")
            return None
        except Exception as e:
            self.logger.error(f"Error in shutdown_server: {e}")
            self.logger.error(f"Traceback: {traceback.format_exc()}")
            return None

    def open_gui(self, host="localhost", management_port=5051):
        pass


if __name__ == "__main__":
    """
    Demo:
      1) Start server on a separate process
      2) Wait a bit for it to bind
      3) Connect with client (same event loop used for all future calls)
      4) Send test data
      5) Shutdown server
    """
    import random

    print("Running BaseUserServerExecutor as a standalone test...")

    tool = BaseUserServerExecutor()
    HOST = "127.0.0.1"
    PORT = 12345

    print(f"Launching server on {HOST}:{PORT} ...")
    server_thread = tool.run_server(host=HOST, port=PORT, open_new_terminal=False)

    # Give the new server process time to bind the port
    time.sleep(2)

    print("Attempting to connect client...")
    tool.connect_client(start_sleep=10, retry_delay=2, max_retries=5)

    if tool.client and tool.client.is_connected:
        print("Client connected! Sending some test data now...")

        test_payload = {
            "numbers": [random.randint(1, 100) for _ in range(5)],
            "message": "Hello from BaseUserServerExecutor!",
        }

        resp = tool.send_data_to_server(test_payload)
        print("Server responded with:", resp)

        print("Requesting server shutdown...")
        shutdown_resp = tool.shutdown_server()
        print("Shutdown response:", shutdown_resp)
    else:
        print("Client never connected. Exiting.")

    print("Joining server thread...")
    server_thread.join()

    print("Done.")
