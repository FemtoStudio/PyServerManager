import unittest
import threading
import time
from server_manager.server import SocketServer

# Mock logger for testing purposes
import logging

logger = logging.getLogger('test_logger')
logger.setLevel(logging.DEBUG)


def data_handler(data):
    logger.info(f"Server received data: {data}")
    return data  # Simple passthrough handler


class TestSocketServer(unittest.TestCase):

    def setUp(self):
        # Initialize and start the server
        self.server = SocketServer(port=5050, data_handler=data_handler)
        self.server_thread = threading.Thread(target=self.server.start_accepting_clients,
                                              kwargs={'return_response_data': True})
        self.server_thread.daemon = True  # Daemonize thread to automatically exit
        self.server_thread.start()
        time.sleep(1)  # Give server time to start

    def tearDown(self):
        # Close the server after the test
        self.server.close_server()

        # Ensure all server threads are stopped
        self.server.client_acceptor.join()
        self.server.management_acceptor.join()

    def test_server_start_and_shutdown(self):
        # Simple test to start and stop the server
        self.assertTrue(self.server.server_ready)  # Check if server is running
        time.sleep(1)  # Allow some time to simulate server activity


if __name__ == '__main__':
    unittest.main()
