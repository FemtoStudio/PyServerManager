# main.py

import logging
import threading
import time
from time import sleep

import numpy as np

# Set up basic logging
logger = logging.getLogger('main_logger')
logger.setLevel(logging.DEBUG)
handler = logging.StreamHandler()
handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(message)s'))
logger.addHandler(handler)

from PyServerManager.server_manager.client import SocketClient
from PyServerManager.execute_thread.execute_manager import ExecuteThreadManager

# Ensure that the ExecuteThread classes are imported or defined in your project
# from your_module import ExecuteThreadManager  # Adjust the import as necessary


def client_thread_function(client_id, test_data):
    # Start the client
    client = SocketClient(host='localhost', port=5050)
    try:
        response = client.attempt_to_send(test_data)
        logger.info(f"Client {client_id} received response: {response}")
    except Exception as e:
        logger.error(f"Client {client_id} encountered an error: {e}")
    finally:
        client.close_client()


def main():
    # Initialize the ExecuteThreadManager

    # Paths to the Python executable and the server script
    python_exe = sys.executable  # Use the same Python interpreter
    script_path = r'E:\ai_projects\ai_portal\PyServerManager\execute_thread\test_scripts\server_script.py'  # Adjust path if necessary

    # Arguments to pass to the server script
    server_args = {
        'port': 5050,
        'return_response_data': True,
    }

    # No pre_cmd or post_cmd in this case
    pre_cmd = None
    post_cmd = None
    export_env = None
    open_new_terminal = True  # Set to True if you want to open in a new terminal
    custom_activation_script = None

    manager = ExecuteThreadManager(
        python_exe=python_exe,
        script_path=script_path,
        export_env=export_env,
        custom_activation_script=custom_activation_script,
    )
    # Start the server using ExecuteThread
    server_thread = manager.get_thread(
        args=server_args,
        pre_cmd=pre_cmd,
        post_cmd=post_cmd,
        open_new_terminal=open_new_terminal,
    )
    server_thread.daemon = False
    logger.info("Starting server thread...")
    server_thread.start()

    # Wait a bit to ensure the server has started
    time.sleep(2)

    # Prepare test data for multiple clients
    num_clients = 5  # Adjust the number of clients as needed
    test_data_list = [
        {
            'message': f'Hello from client {i}',
            'numbers': [i, i + 1, i + 2],
            'array': np.array([i * 10, i * 20, i * 30]),
            'value': i * 10
        }
        for i in range(num_clients)
    ]

    # Start client threads
    client_threads = []
    for i, test_data in enumerate(test_data_list):
        t = threading.Thread(target=client_thread_function, args=(i, test_data))
        t.start()
        client_threads.append(t)

    # Wait for all client threads to finish
    for t in client_threads:
        t.join()

    logger.info("All clients have finished.")

    # Terminate the server
    # logger.info("Terminating server thread...")
    # server_thread.terminate()
    #
    # Clean up threads
    manager.clean_up_threads()


if __name__ == '__main__':
    import sys

    main()
