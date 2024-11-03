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
        # Initialize and start the server on an available port
        self.port = SocketServer.find_available_port()
        self.server = SocketServer(port=self.port, data_handler=data_handler)
        self.server_thread = threading.Thread(target=self.server.start_accepting_clients,
                                              kwargs={'return_response_data': True})
        self.server_thread.start()
        time.sleep(1)  # Give server time to start

    def tearDown(self):
        # Close the server after the test
        self.server.close_server()
        # Wait for server thread to finish
        self.server_thread.join()
        time.sleep(1)  # Give server time to shut down

    def test_server_start_and_shutdown(self):
        # Simple test to start and stop the server
        self.assertTrue(self.server.server_ready, "Server did not start successfully")
        time.sleep(1)  # Allow some time to simulate server activity

    def test_server_client_communication(self):
        # Import the client class
        from server_manager.client import SocketClient

        # Create a client and connect to the server
        client = SocketClient(host='localhost', port=self.port)
        connected = client.connect_to_server()
        self.assertTrue(connected, "Client failed to connect to the server")

        # Send data and wait for response
        test_data = "Hello, Server!"
        response = client.send_data_and_wait_for_response(test_data)
        self.assertEqual(response, test_data, "The response from the server did not match the sent data")

        # Disconnect the client
        client.disconnect_from_server()


if __name__ == '__main__':
    logger.info("Running server tests...")
    unittest.main()
