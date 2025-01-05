# base_async_pickle.py
import asyncio
import socket
from PyServerManager.core.logger import SingletonLogger
from PyServerManager.async_server.message_coder import MessageCoder, HEADER_SIZE

class BaseAsyncPickle:
    """
    A base class with helper methods to read/write the "Pickle + header" protocol
    over an asyncio StreamReader/StreamWriter.
    """
    logger = SingletonLogger.get_instance("PyServerManager")

    @staticmethod
    def find_available_port(host='localhost'):
        """
        Bind to a random free port provided by the OS, then release it.
        Return the port number.
        """
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as temp_sock:
            temp_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            temp_sock.bind((host, 0))  # port=0 => OS assigns ephemeral port
            port = temp_sock.getsockname()[1]
        return port

    async def write_message(
        self,
        writer: asyncio.StreamWriter,
        message_type: str,
        data
    ):
        """
        Encodes and writes a message to the stream, then flushes (drain).
        """
        raw_bytes = MessageCoder.encode_message(message_type, data)

        writer.write(raw_bytes)
        await writer.drain()

    async def read_next_message(
        self,
        reader: asyncio.StreamReader
    ):
        """
        Reads the next complete message (header + payload) from the stream.
        Returns (message_type, decoded_object), or None if we get EOF.
        """

        # Attempt to read the header
        try:
            header = await reader.readexactly(HEADER_SIZE)
        except asyncio.IncompleteReadError:
            print("Server closed before sending a response.")
            return None
        if not header:
            return None  # EOF

        # Parse the header
        message_type, payload_len = MessageCoder.decode_header(header)

        # Read the payload
        payload_data = await reader.readexactly(payload_len)
        if not payload_data:
            return None

        # Unpickle
        obj = MessageCoder.decode_payload(payload_data)
        return (message_type, obj)
