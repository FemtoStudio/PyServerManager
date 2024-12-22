"""
server_runner.py

Starts a SocketServer on the given port with a given data_handler,
then keeps running until forcibly closed (KeyboardInterrupt or the 'quit' command).
"""
import argparse
import base64
import json
import logging
import time
import sys
from server_manager.server import SocketServer

# If you need NumPy or other imports, do them here
import numpy as np


def data_handler(data):
    """
    Example data handler to show data transformation.
    Modify as needed to match your existing logic.
    """
    logging.info(f"Server received data: {data}")
    # Sleep or do some heavy processing
    for i in range(5):
        time.sleep(1)
        logging.debug(f"Processing data iteration {i}")

    # If data is a dict, do transformation
    if isinstance(data, dict):
        modified_data = {}
        for k, v in data.items():
            if isinstance(v, (int, float)):
                modified_data[k] = v + 1
            elif isinstance(v, np.ndarray):
                modified_data[k] = v * 2
            else:
                modified_data[k] = v
        logging.info(f"Server returning modified data: {modified_data}")
        return modified_data
    else:
        return data


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--encoded-args', help='Base64 encoded JSON arguments')
    args = parser.parse_args()

    # Decode the base64 encoded arguments
    decoded_args = base64.b64decode(args.encoded_args).decode('utf-8')
    # Deserialize the JSON string into a dictionary
    data = json.loads(decoded_args)
    # Use 'data' as needed in your script
    print("Received arguments:", data)

    logging.basicConfig(level=logging.DEBUG)
    logger = logging.getLogger("server_runner")
    logger.debug(f"Starting server on {data['host']}:{data['port']}")

    server = SocketServer(port=data['port'], data_handler=data_handler, host=data['host'])
    server.start_accepting_clients(return_response_data=True)

    logger.info("Server is running. Press Ctrl+C to stop or send 'quit' command.")
    try:
        while server.active:
            time.sleep(1)
    except KeyboardInterrupt:
        logger.info("KeyboardInterrupt received; shutting down server.")
    finally:
        server.close_server()
        logger.info("Server has been shut down.")


if __name__ == "__main__":
    main()
