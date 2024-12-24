# base_user_server_executor.py
import time
import logging
import sys
from pathlib import Path

from PyServerManager.core.logger import SingletonLogger
from PyServerManager.server.client import SocketClient
from PyServerManager.templates.base_user_task_executor import BaseUserTaskExecutor


class BaseUserServerExecutor(BaseUserTaskExecutor):
    """
    A specialized template class that runs a server script (via the ExecuteThreadManager)
    and then optionally connects to it via SocketClient.

    Usage Flow:
      1) call run_server(...) -> spawns the server script as a background thread.
      2) call connect_client_async(...) -> attempts to connect in another thread (non-blocking).
      3) (Optionally) call send_data_to_server(...) to interact once connected.
      4) (Optionally) open the PySide6 GUI with open_gui(...).
    """

    # By default, might point to your server_executor.py
    EXECUTOR_SCRIPT_PATH = str(
        (Path(__file__).parent.parent / "executors" / "server_executor.py").resolve()
    )

    def __init__(
            self,
            python_exe: str = None,
            activation_script: str = None,
            env_vars: dict = None,
            logger: logging.Logger = None
    ):
        # Reuse base init: sets up self.executor_manager, self.logger, etc.
        super().__init__(
            python_exe=python_exe,
            activation_script=activation_script,
            env_vars=env_vars,
            logger=logger or SingletonLogger.get_instance("BaseUserServerExecutor"),
        )
        self.client = None  # We'll create a SocketClient as needed
        self.host = None
        self.port = None
        self.management_port = None

    def run_server(self, host="localhost", port=5050, management_port=5051, open_new_terminal=False):
        """
        Run the server in the background via the server_executor script.

        :param host: Host/IP on which the server should listen
        :param port: Port for client connections
        :param management_port: (Optional) separate port for management
        :param open_new_terminal: If True, spawns a new terminal window (no output captured)
        :return: The ExecuteThread object running that server script
        """
        # If your server_executor script expects normal CLI flags like --host, --port, etc.,
        # we'll pass encode_args=False so they appear as such.
        self.host = host
        self.port = port
        self.management_port = management_port or self.port + 1
        self.logger.info(f"Starting server on {host}:{port} (management on {management_port})...")

        args_dict = {
            "host": self.host,
            "port": self.port,
            "management-port": self.management_port
        }

        thread = self.execute(args_dict=args_dict, encode_args=True, open_new_terminal=open_new_terminal)
        self.client = SocketClient(host=self.host, port=self.port)
        self.client.attempting_to_connect(start_sleep=2)
        return thread

    def connect_client_async(
            self,
            host=None,
            port=None,
            start_sleep=1,
            retry_delay=2,
            max_retries=None
    ):
        """
        Initiate asynchronous attempts to connect to the server,
        without blocking the main thread.

        Internally calls SocketClient.attempting_to_connect(...),
        which spawns a separate thread to keep trying until success
        or max_retries is reached.

        :param host: Host to connect
        :param port: Port to connect
        :param start_sleep: Seconds to wait before the first connection attempt
        :param retry_delay: Seconds to wait between connection attempts
        :param max_retries: How many times to attempt; None = infinite
        :return: None
        """
        host = host or self.host
        port = port or self.port
        # Create the SocketClient if we haven't already
        if self.client is None:
            self.client = SocketClient(host=host, port=port)
        else:
            # If self.client is already created, set new host/port if needed
            self.client.host = host
            self.client.port = port

        self.logger.info(
            f"[AsyncClientConnect] Attempting to connect to {host}:{port} "
            f"with start_sleep={start_sleep}, retry_delay={retry_delay}, max_retries={max_retries}"
        )
        # This does NOT block; it spawns a separate thread inside SocketClient
        self.client.attempting_to_connect(
            host=host,
            port=port,
            start_sleep=start_sleep,
            retry_delay=retry_delay,
            max_retries=max_retries
        )

    def send_data_to_server(self, data, timeout=60):
        """
        Attempt to send data to the server via SocketClient.

        :param data: (dict or any picklable)
        :param timeout: how long to wait for the server's response
        :return: response object from the server or None if failure
        """
        if not self.client or not self.client.is_client_connected:
            self.logger.warning("No active client. Please call connect_client_async() (or connect) first.")
            return None

        try:
            response = self.client.attempt_to_send(data, timeout=timeout)
            self.logger.info(f"Server response: {response}")
            return response
        except Exception as e:
            self.logger.error(f"Error sending data to server: {e}")
            return None

    def open_gui(self, host="localhost", management_port=5051):
        """
        (Optional) Launch the PySide6-based GUI for managing the server.
        Typically you'd do: pyservermanager gui --host xxx --port yyy
        But here's an example if you want to embed it in code.

        NOTE: This blocks until the GUI closes, because QApplication.exec() is blocking.
        """
        try:
            from PySide6.QtWidgets import QApplication
            from PyServerManager.server.server_manager import ServerManager
        except ImportError:
            self.logger.error("PySide6 not installed. Cannot open server manager GUI.")
            return

        app = QApplication(sys.argv)
        manager = ServerManager(default_host=host, default_port=management_port)
        manager.show()
        self.logger.info(f"Launching GUI for host={host}, management_port={management_port}")
        sys.exit(app.exec())


if __name__ == "__main__":
    """
    Quick test to confirm that BaseUserServerExecutor can:
      1) Start the server
      2) Connect a client (asynchronously)
      3) Optionally send some data to check the response
    """
    print("Running BaseUserServerExecutor as a standalone test...")
    tool = BaseUserServerExecutor()

    # 1) Start the server in background
    HOST = "127.0.0.1"
    PORT = SocketClient.find_available_port()
    management_port = PORT + 1
    print(f"Starting server on {HOST}:{PORT} (management on {PORT+1})...")
    thread = tool.run_server(host=HOST, port=PORT, management_port=management_port, open_new_terminal=True)
    print(
        f"Server started. You can connect to it with SocketClient(host='{HOST}', port={PORT})."
        f" (You can also use the GUI with tool.open_gui(host='{HOST}', management_port={PORT+1}))"
    )
    # thread.join()
    # 3) Check if the client is connected
    for i in range(10):
        print(
            f"Checking if client is connected... (attempt {i+1}/{10})",
            end="\r" if i < 9 else "\n"
        )
        time.sleep(1)
        if tool.client and tool.client.is_client_connected:
            print("Client is connected! Let's send some test data.")
            response = tool.send_data_to_server({"test": "Hello from base_user_server_executor!"})
            print("Server responded:", response)
        else:
            print("Client did not connect within 10 seconds. Exiting.")

    print("Test run complete. Check logs for server output and any responses.")
