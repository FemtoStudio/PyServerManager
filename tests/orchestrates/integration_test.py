"""
integration_test.py

Orchestrates the server, multiple clients, and the PySide6 GUI via ExecuteThreadManager.
"""
import os
import sys
import time
import logging
from core.execute_manager import ExecuteThreadManager
from server.client import SocketClient

HOST = '127.0.0.1'
PORT = SocketClient.find_available_port()

def main():
    logger = logging.getLogger("integration_test")
    logging.basicConfig(level=logging.DEBUG)

    # 1) Identify the python interpreter
    python_exe = sys.executable  # current Python

    # 2) Paths to your runner scripts
    this_dir = os.path.dirname(os.path.abspath(__file__))
    server_script = os.path.join(this_dir, "server_runner.py")
    client_script = os.path.join(this_dir, "client_runner.py")
    gui_script = os.path.join(this_dir, "..", "..", "server", "server_manager.py")
    # ^ Adjust the path to wherever your `server_manager.py` is located
    #   For example, if "server_manager.py" is at:
    #   PyServerManager/server_manager/server_manager.py,
    #   then you'd do:
    #   gui_script = os.path.join(this_dir, "..", "server_manager", "server_manager.py")

    # 3) Create manager
    manager = ExecuteThreadManager(
        python_exe=python_exe,
        script_path=server_script,       # By default, we'll run the SERVER script
        export_env={},
        custom_activation_script=None,
        callback=None,
        custom_logger=logger
    )

    # 4) Start the server (inline)
    server_args = {
        "port": PORT,
        "host": HOST
    }
    server_thread = manager.get_thread(
        args=server_args,
        open_new_terminal=False  # inline => we capture logs in server_thread.output
    )
    logger.info("Starting server process...")
    server_thread.start()

    # Give the server a moment to start listening
    time.sleep(3)

    # 5) Launch multiple clients
    num_clients = 3
    client_threads = []
    for i in range(num_clients):
        client_thread = manager.get_thread(
            args={"host": HOST, "port": PORT, "client-id": i},
            script_path=client_script,   # override to run the client
            open_new_terminal=False
        )
        logger.info(f"Starting client {i} process...")
        client_thread.start()
        client_threads.append(client_thread)

    # 6) Optionally, let's LAUNCH THE GUI in a NEW TERMINAL:
    #    So you see the PySide6 window. The user can connect to "localhost:5051" or
    #    "localhost:5050", depending on how you set up your server. If your server
    #    management port is 5051, you can manually change it in the GUI's text fields.
    gui_thread = manager.get_thread(
        args={"host": HOST, "port": PORT},                  # We’re not passing base64-args here;
                                  # you can modify server_manager.py to parse them if desired
        script_path=gui_script,   # override to run the GUI
        open_new_terminal=True    # Launch in a new console/terminal window
    )
    logger.info("Launching server_manager GUI in a new terminal...")
    gui_thread.start()

    # 7) Wait for all clients to finish
    for ct in client_threads:
        ct.join()
        logger.info(f"Client thread done. Exit code={ct.exit_code}")
        if ct.output:
            logger.debug(f"Client output:\n{ct.output}")

    # (At this point, the GUI is still running in a separate window, and the server is
    #  still running inline.)
    
    # 8) Terminate the server
    #    If we want to forcibly kill the server (and the GUI if desired), do manager.terminate_all().
    #    If you'd rather do a graceful server shutdown, you'd send a 'quit' command from a client.
    logger.info("Terminating server and all inline processes.")
    manager.terminate_all()

    # 9) Join the server thread
    server_thread.join()
    logger.info(f"Server thread done. Exit code={server_thread.exit_code}")
    if server_thread.output:
        logger.debug(f"Server output:\n{server_thread.output}")

    # 10) The GUI, launched in a new terminal, is also forcibly closed by terminate_all().
    #     But if you prefer to let the GUI remain open, you can skip calling terminate_all() on it.

    # 11) Clean up any leftover threads
    manager.clean_up_threads()
    logger.info("Integration test complete.")


if __name__ == "__main__":
    main()
