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

import select

from base import ServerClientBase
from utils import MessageReceiver


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
                self.status = 'No Response Received'
                self.logger.debug('No response received, server might have closed the connection.')
        except socket.timeout:
            self.status = 'Timeout'
            self.logger.error('Timeout reached while waiting for response.')
            raise
        except Exception as e:
            self.status = 'Error'
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

    def connect_to_server(self):
        """
        Establishes a connection to the server.

        This method creates a socket and attempts to connect to the server at the
        specified host and port. If successful, the connection is maintained until
        explicitly closed.

        @return: True if the connection was successful, False otherwise.
        @rtype: bool
        @raises ConnectionRefusedError: If the connection is refused by the server.
        @raises Exception: For other errors encountered during the connection process.
        """
        try:
            if self.client is not None:
                self.client.close()
            self.client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

            self.logger.debug(f"Trying to connect to {self.host}:{self.port}")
            self.client.connect((self.host, self.port))
            self.client.setblocking(True)
            self.is_client_connected = True
            self.logger.info(f"Successfully connected to server at {self.host}:{self.port}")
            self.status = 'Connected'
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

    def close_client(self):
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
        Closes the server, stopping all active connections and shutting down the server socket.

        This method is part of the server-side logic that ensures the server is gracefully
        shut down, including closing active client connections and releasing socket resources.
        """
        self.active = False
        self.logger.info("Initiating server shutdown...")
        # Copy the keys to avoid changing dict size during iteration
        client_addrs = list(self.client_connections.keys())
        for addr in client_addrs:
            self.close_connection(addr)
        # Shut down the server socket
        if self.server_socket.fileno() != -1:
            try:
                self.server_socket.shutdown(socket.SHUT_RDWR)
                self.logger.info("Server socket shutdown successfully.")
            except OSError as e:
                if e.errno == 10057:
                    self.logger.warning("Server socket is not connected; nothing to shutdown.")
                else:
                    self.logger.error(f"Non-critical error during server socket shutdown: {e}")
            except Exception as e:
                self.logger.error(f"Unexpected error during server socket shutdown: {e}")
        # Close the server socket
        try:
            if self.server_socket.fileno() != -1:
                self.server_socket.close()
                self.logger.info("Server socket closed successfully.")
        except Exception as e:
            self.logger.error(f"Error closing server socket: {e}")
        self.server_ready = False
        self.client_connections.clear()
        self.client_threads.clear()
        self.logger.info("Server has been fully shut down.")

    def query_server_ready(self):
        """
        Sends a command to the server to check if it is ready.

        This method sends a 'is_server_ready' command to the server and waits for a response.
        If the server responds with 'yes', it indicates that the server is ready to process
        requests. Otherwise, it returns False.

        @return: True if the server is ready, False otherwise.
        @rtype: bool
        """
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
                        response = payload.decode('ascii')
                        return response == 'yes'
        return False
