"""
client_runner.py

Connects to a SocketServer, sends test data, waits for a response, and prints it.
Exits once the response is received or on error.
"""
import argparse
import base64
import json
import logging
import numpy as np
import sys
import time
from server_manager.client import SocketClient


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
    
    parser.add_argument("--host", default="localhost", help="Server host")
    parser.add_argument("--port", type=int, default=5050, help="Server port")
    parser.add_argument("--client-id", type=int, default=0, help="ID of the client (for logging)")
    args = parser.parse_args()

    logging.basicConfig(level=logging.DEBUG)
    logger = logging.getLogger(f"client_runner_{data['client-id']}")

    # Example data to send. Adjust as needed or parse from CLI.
    test_data = {
        "message": f"Hello from client {data['client-id']}",
        "value": data['client-id'] * 10,
        "array": np.array([data['client-id'], data['client-id'] + 1, data['client-id'] + 2])
    }
    logger.info(f"Client {data['client-id']} connecting to {data['host']}:{data['port']}...")

    client = SocketClient(host=data['host'], port=data['port'])
    try:
        # Attempt a single send/receive
        response = client.attempt_to_send(test_data, timeout=30)
        logger.info(f"Client {data['client-id']} got response: {response}")
    except Exception as e:
        logger.error(f"Client {data['client-id']} error: {e}")
    finally:
        logger.info(f"Client {data['client-id']} closing socket.")
        client.disconnect_from_server()
        # or client.close_server() if you intend to request server shutdown


if __name__ == "__main__":
    main()
