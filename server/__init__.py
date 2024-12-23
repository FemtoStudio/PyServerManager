# main.py
# Mock logger for testing purposes
import logging
import threading
import time
from time import sleep

import numpy as np

logger = logging.getLogger('test_logger')
logger.setLevel(logging.DEBUG)

# Set logger level to DEBUG for detailed output
logger.setLevel(logging.DEBUG)


# Define the data handler function for the server
def data_handler(data):
    # This function will modify the received data and return it
    logger.info(f"Server received data: {data}")
    for i in range(10):
        sleep(1)
        logger.debug(f"Processing data... {i}")

    # Let's assume data is a dictionary
    if isinstance(data, dict):
        # For example, increment all numeric values by 1
        modified_data = {}
        for key, value in data.items():
            if isinstance(value, (int, float)):
                modified_data[key] = value + 1
            elif isinstance(value, np.ndarray):
                modified_data[key] = value * 2  # Multiply NumPy arrays by 2
            else:
                modified_data[key] = value
        logger.info(f"Server modified data: {modified_data}")
        return modified_data
    else:
        # If data is not a dict, just return it as is
        return data


def client_thread_function(client_id, test_data):
    # Start the client
    client = SocketClient(host='localhost', port=5050)
    try:
        response = client.attempt_to_send(test_data)
        print(f"Client {client_id} received response:", response)
    except Exception as e:
        print(f"Client {client_id} encountered an error: {e}")
    finally:
        client.close_client()


if __name__ == '__main__':
    from client import SocketClient
    from server import SocketServer

    # Start the server
    server = SocketServer(port=5050, data_handler=data_handler)
    # server.run_server(return_response_data=True)
    server.start_accepting_clients(return_response_data=True)
    time.sleep(1)  # Give the server a moment to start

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
    print("server Queue length", server.request_queue.qsize())
    # Wait for all client threads to finish
    for t in client_threads:
        print("server Queue length", server.request_queue.qsize())
        t.join()

    # Close the server
    server.close_server()
