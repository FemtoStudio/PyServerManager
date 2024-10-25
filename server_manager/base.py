import pickle
import socket
import struct

import logging
# Configure logging
logging.basicConfig(level=logging.INFO)  # Configure basic logging
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)



class ServerClientBase:
    """
    Base class for managing server and client connections.

    Attributes:
        client_threads (dict): Stores active client threads.
        client_connections (dict): Stores active client connections with addresses as keys.
        logger (Logger): Logger instance for logging messages.
    """

    def __init__(self):
        """
        Initializes the ServerClientBase instance.

        Initializes the client_threads and client_connections attributes
        and sets up the logger.
        """
        self.client_threads = {}
        self.client_connections = {}
        self.logger = logger

    def close_connection(self, addr):
        """
        Closes the connection for a given client address.

        @param addr: The address of the client to close the connection for.
        @raise NotImplementedError: This method should be implemented by subclasses.
        """
        raise NotImplementedError

    def close_server(self):
        """
        Closes the server and performs cleanup tasks.

        @raise NotImplementedError: This method should be implemented by subclasses.
        """
        raise NotImplementedError

    @staticmethod
    def find_available_port():
        """
        Finds and returns an available port on the system.

        @return: An available port number.
        @rtype: int
        """
        temp_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        temp_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        temp_sock.bind(('', 0))
        port = temp_sock.getsockname()[1]
        temp_sock.close()
        return port

    @staticmethod
    def encode_data(message_type, data):
        """
        Encodes data to be sent over a socket.

        Serializes the data using pickle and constructs a header with the message type and payload length.

        @param message_type: The type of message, limited to 4 characters.
        @type message_type: str
        @param data: The data to be serialized and encoded.
        @type data: Any serializable object
        @return: The encoded data with a header and serialized payload.
        @rtype: bytes
        """
        serialized_data = pickle.dumps(data)
        payload_length = len(serialized_data)
        header = message_type.encode('ascii')[:4].ljust(4, b' ')
        header += struct.pack('!I', payload_length)
        return header + serialized_data
