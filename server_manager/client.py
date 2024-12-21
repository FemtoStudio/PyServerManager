# client.py
"""
Socket Client Module for Connecting and Communicating with a Server

This module implements a socket-based client that can connect to a server, send data,
and wait for responses. It includes methods for establishing a connection, sending data,
waiting for responses, and closing the connection. It also provides functionality for
checking the server's readiness state.

## Components:
- **SocketClient**: A client class that handles communication with a server over a socket connection.
- **MessageReceiver**: A utility class used to buffer and parse incoming data from the server.

## Data Flow:
1. **Connection Establishment**:
   - The client connects to the server using the specified host and port. If successful,
     the connection is maintained until explicitly closed.

2. **Data Exchange**:
   - Data is sent to the server using the `send_data_and_wait_for_response` method. The client
     waits for a response from the server or raises an error if no response is received within the timeout period.

3. **Server Query**:
   - The client can send a command to check if the server is ready to process requests.

## Error Handling:
- Proper exceptions are raised in cases of connection failure, timeout, or other communication errors.
"""

import pickle
import socket
import threading
import time

import select

from .base import ServerClientBase
from .utils import MessageReceiver


class SocketClient(ServerClientBase):
    """
    A socket client for connecting to and communicating with a server.

    This class provides methods to establish a connection, send data, receive responses,
    and close the connection. It also supports querying the server's readiness state.

    Attributes:
        is_client_connected (bool): Indicates if the client is connected to the server.
        host (str): The server's host address.
        port (int): The server's port number.
        client (socket): The client socket used for communication.
    """

    def __init__(self, host='localhost', port=5050):
        """
         Initializes the socket client with the specified host and port.

         @param host: The server's host address.
         @type host: str
         @param port: The server's port number.
         @type port: int
         """
        super().__init__()
        self.is_client_connected = False
        self.host = host
        self.port = port
        self.client = None  # Initialize client as None
        self.status = 'Initialized'
        self.thread_list = []  # List to keep track of reconnect threads

    def send_data_and_wait_for_response(self, data, timeout=60):
        """
        Sends data to the server and waits for a response.

        This method encodes the data, sends it to the server, and waits for a response
        within the specified timeout period. If a response is received, it is returned;
        otherwise, an error is raised.

        @param data: The data to send to the server.
        @type data: object
        @param timeout: The timeout in seconds for waiting for a response.
        @type timeout: int
        @return: The decoded response from the server, if any.
        @rtype: object or None
        @raises socket.timeout: If the timeout is reached while waiting for a response.
        @raises Exception: If an error occurs during data transmission or reception.
        """
        try:
            self.status = 'Sending Data'
            encoded_data = self.encode_data('DATA', data)
            self.client.sendall(encoded_data)
            self.status = 'Waiting for Response'
            self.logger.debug('Data sent, waiting for response with timeout {}'.format(timeout))
            receiver = MessageReceiver()
            self.client.settimeout(timeout)
            data = self.client.recv(4096)
            if data:
                messages = receiver.feed_data(data)
                for message_type, payload in messages:
                    if message_type == 'DATA':
                        decoded_response = pickle.loads(payload)
                        self.status = 'Received Response'
                        return decoded_response
                    elif message_type == 'RESP':
                        response = payload.decode('ascii')
                        self.logger.debug(f"Received response: {response}")
                        self.status = 'Received Response'
                return None
            else:
                # Connection closed by server
                self.status = 'No Response Received'
                self.is_client_connected = False  # Update the connection status
                self.logger.debug('No response received, server might have closed the connection.')
                raise ConnectionError('Server closed the connection.')
        except socket.timeout:
            self.status = 'Timeout'
            self.logger.error('Timeout reached while waiting for response.')
            raise
        except (ConnectionResetError, BrokenPipeError, ConnectionAbortedError) as e:
            self.status = 'Disconnected'
            self.is_client_connected = False  # Update the connection status
            self.logger.error(f"Connection lost during data transmission: {e}")
            raise
        except Exception as e:
            self.status = 'Error'
            self.is_client_connected = False  # Update the connection status
            self.logger.error(f"An error occurred while sending data and waiting for response: {e}")
            raise

    def attempt_to_send(self, data_to_send, timeout=60):
        """
        Attempts to send data to the server once and waits for a response.

        If the client is not connected, this method tries to connect to the server first.
        It then sends the specified data and waits for a response, raising an exception
        if the connection fails or if data transmission is unsuccessful.

        @param data_to_send: The data to send to the server.
        @type data_to_send: object
        @param timeout: The timeout in seconds for waiting for a response.
        @type timeout: int
        @return: The response received from the server.
        @rtype: object
        @raises ConnectionError: If unable to connect to the server.
        @raises Exception: If an error occurs during sending or receiving data.
        """
        if not self.is_client_connected:
            self.logger.info(f"Client is not connected. Attempting to connect to {self.host}:{self.port}")
            connected = self.connect_to_server()
            if not connected:
                self.logger.error(f"Unable to connect to server at {self.host}:{self.port}.")
                raise ConnectionError(f"Unable to connect to server at {self.host}:{self.port}.")
        try:
            response = self.send_data_and_wait_for_response(data_to_send, timeout=timeout)
            return response
        except Exception as e:
            self.logger.error(f"Failed to send data: {e}")
            raise

    def connect_to_server(self, host=None, port=None):
        """
        Establishes a connection to the server.

        This method creates a socket and attempts to connect to the server at the
        specified host and port. If successful, the connection is maintained until
        explicitly closed.

        @param host: The server's host address, optional.
        @type host: str
        @param port: The server's port number, optional.
        @type port: int

        @return: True if the connection was successful, False otherwise.
        @rtype: bool
        @raises ConnectionRefusedError: If the connection is refused by the server.
        @raises Exception: For other errors encountered during the connection process.
        """
        # Determine the target host and port
        target_host = host or self.host
        target_port = port or self.port

        # Check if the client is already connected
        if self.is_client_connected:
            if self.host == target_host and self.port == target_port:
                self.logger.warning(f"Client is already connected to {self.host}:{self.port}")
                return True  # Already connected to the desired server
            else:
                self.logger.warning(
                    f"Client is already connected to {self.host}:{self.port}. "
                    f"To connect to a different server ({target_host}:{target_port}), "
                    "please close the current connection first."
                )
                return False  # Cannot proceed without closing the existing connection

        # Update host and port
        self.host = target_host
        self.port = target_port

        if not self.host or not self.port:
            self.logger.error("Host and port must be specified to connect to the server.")
            return False

        try:
            # Initialize the client socket
            self.client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

            self.logger.debug(f"Trying to connect to {self.host}:{self.port}")
            self.client.connect((self.host, self.port))
            self.client.setblocking(True)
            self.is_client_connected = True
            self.status = 'Connected'
            self.logger.info(f"Successfully connected to server at {self.host}:{self.port}")
            return True
        except ConnectionRefusedError:
            self.logger.warning(f"Connection to server at {self.host}:{self.port} refused.")
            if self.client is not None:
                self.client.close()
            self.is_client_connected = False
            return False
        except Exception as e:
            self.logger.error(f"Error while connecting: {e}")
            if self.client is not None:
                self.client.close()
            self.is_client_connected = False
            return False

    def is_server_running(self):
        """
        Checks if the server is running.

        This method attempts to connect to the server's port to check if the server is running.

        Returns:
            bool: True if the server is running, otherwise False.
        """
        test_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            test_socket.connect((self.host, self.port))
            test_socket.close()
            return True
        except socket.error:
            return False

    def attempting_to_connect(self, host=None, port=None, start_sleep=0, retry_delay=5, max_retries=None):
        """
        Starts a new thread to attempt to connect to the server continuously until successful.

        @param host: Optional server host address.
        @param port: Optional server port.
        @param start_sleep: Initial delay before attempting to connect, in seconds.
        @param retry_delay: Delay between retries in seconds.
        @param max_retries: Maximum number of retries. If None, retries indefinitely.
        """

        thread = threading.Thread(
            target=self._attempt_connect_loop,
            args=(host, port, start_sleep, retry_delay, max_retries)
        )
        thread.daemon = True
        thread.start()
        self.logger.debug('Attempting to connect on a separate thread')
        self.thread_list.append(thread)

    def _attempt_connect_loop(self, host=None, port=None, start_sleep=0, retry_delay=5, max_retries=None):
        """
        Attempts to connect to the server continuously until successful.

        @param host: Hostname to connect to.
        @param port: Port number to connect to.
        @param start_sleep: Initial delay in seconds before starting connection attempts.
        @param retry_delay: Delay between retries in seconds.
        @param max_retries: Maximum number of retries. If None, retries indefinitely.
        """
        if start_sleep > 0:
            time.sleep(start_sleep)

        self.host = host or self.host
        self.port = port or self.port

        retries = 0
        while not self.is_client_connected:
            connected = self.connect_to_server()
            if connected:
                self.logger.info(f"Successfully connected to server at {self.host}:{self.port}")
                break
            else:
                if max_retries is not None and retries >= max_retries:
                    self.logger.error(f"Failed to connect to the server after {retries} attempts.")
                    break
                retries += 1
                self.logger.info(f"Retrying connection to server (Attempt {retries}) at {self.host}:{self.port}")
                time.sleep(retry_delay)

    def disconnect_from_server(self):
        """
        Closes the client socket.

        This method safely closes the client socket and ensures that all resources
        are cleaned up. It also sets the connection status to False.
        """
        if self.client:
            try:
                self.client.close()
                self.status = 'Closed'
                self.logger.info("Client socket closed.")
            except OSError as e:
                self.status = 'Error'
                self.logger.error(f"Error closing client socket: {e}")
            finally:
                self.client = None
                self.is_client_connected = False

    def close_server(self):
        """
        Sends the 'quit' command to the server to initiate server shutdown.

        This method encodes the 'quit' command and sends it to the server. If successful,
        the server should shut down. It raises an exception if there is a connection issue.
        """

        try:
            close_command = self.encode_data('CMD', 'quit')
            self.client.sendall(close_command)
            self.logger.info("Close command sent to the server.")
            self.is_client_connected = False
        except Exception as e:
            self.logger.error(f"Failed to send close command to server: {e}")
            raise

    def query_server_ready(self):
        try:
            query_command = self.encode_data('CMD', 'is_server_ready')
            self.client.sendall(query_command)
            receiver = MessageReceiver()
            ready = select.select([self.client], [], [], 10)
            if ready[0]:
                data = self.client.recv(1024)
                if data:
                    messages = receiver.feed_data(data)
                    for message_type, payload in messages:
                        if message_type == 'RESP':
                            response = pickle.loads(payload)  # Unpickle the payload
                            return response == 'yes'
                else:
                    # Connection closed by server
                    self.is_client_connected = False
                    self.logger.debug('No response received, server might have closed the connection.')
                    return False
            else:
                self.logger.debug('No response from server within timeout.')
                return False
        except (ConnectionResetError, BrokenPipeError, ConnectionAbortedError) as e:
            self.is_client_connected = False
            self.logger.error(f"Connection lost during server query: {e}")
            return False
        except Exception as e:
            self.logger.error(f"Error during server query: {e}")
            return False

