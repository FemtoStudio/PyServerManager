# server_script.py

import argparse
import base64
import json
import logging
import sys
import threading
from time import sleep

import numpy as np

# Set up basic logging
logger = logging.getLogger('server_logger')
logger.setLevel(logging.DEBUG)
handler = logging.StreamHandler(sys.stdout)
handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(message)s'))
logger.addHandler(handler)


def data_handler(data):
    logger.info(f"Server received data: {data}")
    for i in range(10):
        sleep(0.1)  # Reduced sleep time for demonstration purposes
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


def main():
    from PyServerManager.server_manager.server import SocketServer

    parser = argparse.ArgumentParser()
    parser.add_argument('--encoded-args', help='Base64 encoded JSON arguments')
    args = parser.parse_args()

    if args.encoded_args:
        decoded_args = base64.b64decode(args.encoded_args).decode('utf-8')
        config = json.loads(decoded_args)
    else:
        config = {}

    port = config.get('port', 5050)
    return_response_data = config.get('return_response_data', True)

    server = SocketServer(port=port, data_handler=data_handler)
    logger.info(f"Starting server on port {port}")
    server_thread = threading.Thread(
        target=server.start_accepting_clients,
        kwargs={'return_response_data': return_response_data},
        daemon=True  # Make the thread a daemon so it doesn't block exit
    )
    server_thread.start()

    # Keep the main thread alive
    try:
        while True:
            sleep(1)
    except KeyboardInterrupt:
        logger.info("Shutting down server...")
        server.close_server()
        server_thread.join()



if __name__ == '__main__':
    main()
