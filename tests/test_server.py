
import unittest
import threading
import time
import numpy as np
from server_manager.server import SocketServer
from server_manager.client import SocketClient

# Mock logger for testing purposes
import logging
logger = logging.getLogger('test_logger')
logger.setLevel(logging.DEBUG)

def data_handler(data):
    logger.info(f"Server received data: {data}")
    if isinstance(data, dict):
        modified_data = {}
        for key, value in data.items():
            if isinstance(value, (int, float)):
                modified_data[key] = value + 1
            elif isinstance(value, np.ndarray):
                modified_data[key] = value * 2
            else:
                modified_data[key] = value
        return modified_data
    return data

class TestSocketServer(unittest.TestCase):
    
    def setUp(self):
        # Initialize and start the server
        self.server = SocketServer(port=5050, data_handler=data_handler)
        server_thread = threading.Thread(target=self.server.start_accepting_clients, kwargs={'return_response_data': True})
        server_thread.daemon = True  # Daemonize thread to automatically exit
        server_thread.start()
        time.sleep(1)  # Give server time to start

    def tearDown(self):
        # Close the server after the test
        self.server.close_server()

    def test_server_accept_client(self):
        # Check if server is accepting connections and handling data
        client = SocketClient(host='localhost', port=5050)
        test_data = {'message': 'test', 'value': 42, 'array': np.array([1, 2, 3])}
        response = client.attempt_to_send(test_data)
        self.assertIsInstance(response, dict)
        self.assertEqual(response['value'], 43)  # Check if value is incremented
        self.assertTrue((response['array'] == np.array([2, 4, 6])).all())  # Check array multiplication
        client.close_client()

if __name__ == '__main__':
    unittest.main()
