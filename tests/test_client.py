
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

class TestSocketClient(unittest.TestCase):
    
    def setUp(self):
        # Initialize and start the server for client testing
        self.server = SocketServer(port=5050, data_handler=data_handler)

        server_thread = threading.Thread(target=self.server.start_accepting_clients, kwargs={'return_response_data': True})
        server_thread.daemon = True  # Daemonize thread to automatically exit
        server_thread.start()
        time.sleep(1)  # Give server time to start

    def tearDown(self):
        # Close the server after the test
        self.server.close_server()

    def test_client_send_data(self):
        # Test client connection and data retrieval
        client = SocketClient(host='localhost', port=5050)
        test_data = {
            'message': 'Client test',
            'numbers': [1, 2, 3],
            'array': np.array([10, 20, 30]),
            'value': 5
        }
        response = client.attempt_to_send(test_data)
        self.assertIsInstance(response, dict)
        self.assertEqual(response['value'], 6)  # Check if value is incremented
        self.assertTrue((response['array'] == np.array([20, 40, 60])).all())  # Check array multiplication
        client.close_client()

if __name__ == '__main__':
    unittest.main()
