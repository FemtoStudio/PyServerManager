# utils.py
"""
Server Utilities for Message Handling and Singleton Management

This module contains utility classes to assist with message receiving, buffering,
and managing singleton instances in a server context. It is used to process incoming
data streams, handle communication between clients and servers, and ensure that
certain objects (like servers) maintain a singleton instance per port.

## Components:
- **MessageReceiver**: Buffers and processes incoming byte streams, extracting messages
  based on a predefined message header and payload structure.
- **SingletonMeta**: A metaclass that ensures singleton behavior for classes, particularly
  useful in scenarios where only one instance of a class (such as a server) should exist
  per port or configuration.
- **safe_eval**: A utility function to safely parse a string representation of an address
    tuple into a tuple.

## Data Flow:
1. **Message Receiving:**
   - Data is continuously fed into the `MessageReceiver` via the `feed_data` method.
   - The receiver extracts messages based on a fixed header size and payload length.
   - Complete messages are returned in the form of a list of tuples, each containing
     the message type and the message payload.

2. **Singleton Management:**
   - The `SingletonMeta` class ensures that a single instance of any class using this
     metaclass is created per unique configuration (e.g., port number).
   - Once an instance is created for a specific configuration, subsequent calls will return
     the same instance rather than creating a new one.

3. **Safe Evaluation:**
    - The `safe_eval` function safely parses a string representation of an address tuple
        into a tuple, handling exceptions and raising errors for invalid input strings.

## Thread Safety:
- The `SingletonMeta` implementation allows safe singleton behavior even when accessed
  from different threads, ensuring that only one instance is created.
"""

import logging
import struct

# Configure logging
logging.basicConfig(level=logging.INFO)  # Configure basic logging
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


class MessageReceiver:
    """
    Handles buffering and extraction of messages from incoming byte streams.

    The `MessageReceiver` class is responsible for managing an internal buffer
    that receives data in chunks, extracting complete messages based on a fixed-size
    header and a dynamic payload length.

    Attributes:
        buffer (bytes): The internal buffer storing incoming data.
        header_size (int): The fixed size of the message header (8 bytes).
        expected_payload_size (int or None): The size of the expected message payload.
        message_type (str or None): The type of the current message being processed.
    """

    def __init__(self):
        """
        Initializes the MessageReceiver with an empty buffer and default message settings.
        """
        self.buffer = b''
        self.header_size = 8
        self.expected_payload_size = None
        self.message_type = None

    def feed_data(self, data):
        """
        Feeds incoming data into the buffer and extracts complete messages.

        This method adds incoming data to the internal buffer and attempts to extract
        complete messages based on the message header (first 8 bytes). Once a complete
        message is found, it is removed from the buffer and returned as part of a list
        of (message_type, payload) tuples.

        @param data: Incoming data to be processed.
        @type data: bytes
        @return: A list of tuples containing the message type and payload for each complete message.
        @rtype: list[tuple[str, bytes]]
        """
        self.buffer += data
        messages = []
        while True:
            if self.expected_payload_size is None:
                if len(self.buffer) >= self.header_size:
                    # Extract header
                    self.message_type = self.buffer[:4].decode('ascii').strip()
                    self.expected_payload_size = struct.unpack('!I', self.buffer[4:8])[0]
                    self.buffer = self.buffer[8:]
                else:
                    # Not enough data for header
                    break
            if self.expected_payload_size is not None:
                if len(self.buffer) >= self.expected_payload_size:
                    payload = self.buffer[:self.expected_payload_size]
                    self.buffer = self.buffer[self.expected_payload_size:]
                    messages.append((self.message_type, payload))
                    # Reset for next message
                    self.expected_payload_size = None
                    self.message_type = None
                else:
                    # Not enough data for payload
                    break
        return messages


class SingletonMeta(type):
    """
    A metaclass that ensures a class has only one instance per unique configuration.

    The `SingletonMeta` metaclass is used to enforce the singleton pattern. This ensures
    that only one instance of a class exists for a given configuration, such as a specific
    port number. If an instance with the same configuration already exists, it is returned;
    otherwise, a new instance is created.

    Attributes:
        _instances (dict): A dictionary storing singleton instances, with the configuration
        (such as the port number) as the key.
    """
    _instances = {}

    def __call__(cls, *args, **kwargs):
        """
        Overrides the call method to ensure singleton behavior.

        This method checks if an instance already exists for the given configuration (e.g., port number).
        If it exists, the existing instance is returned; otherwise, a new instance is created and stored.

        @param args: Positional arguments passed to the class initializer.
        @param kwargs: Keyword arguments, including 'port' which determines the unique configuration.
        @return: A singleton instance of the class.
        @rtype: object
        """
        port = kwargs.get('port', None)
        if port is not None:
            if port not in cls._instances:
                instance = super().__call__(*args, **kwargs)
                cls._instances[port] = instance
            return cls._instances[port]
        else:
            return super().__call__(*args, **kwargs)


def safe_eval(addr_str):
    """
    Safely parses a string representation of an address tuple into a tuple.

    Args:
        addr_str (str): The address string to parse, e.g., "('127.0.0.1', 12345)"

    Returns:
        tuple: A tuple containing the IP address as a string and the port as an integer.

    Raises:
        ValueError: If the string cannot be parsed into a valid address tuple.
    """
    try:
        # Remove parentheses and single quotes
        addr_str = addr_str.strip("() ").replace("'", "")
        # Split the string into IP and port
        ip_str, port_str = addr_str.split(",")
        ip = ip_str.strip()
        port = int(port_str.strip())
        return (ip, port)
    except Exception as e:
        raise ValueError(f"Invalid address string: {addr_str}") from e
