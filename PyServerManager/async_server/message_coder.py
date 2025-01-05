# message_coder.py
import pickle
import struct

HEADER_SIZE = 8
MESSAGE_TYPE_SIZE = 4

class MessageCoder:
    """
    Encodes and decodes messages with a 4-byte message_type + 4-byte length header,
    followed by a pickle-serialized payload.
    """

    @staticmethod
    def encode_message(message_type: str, obj) -> bytes:
        """
        :param message_type: Up to 4 ASCII chars, e.g. 'DATA', 'CMD ', etc.
        :param obj: A Python object to pickle
        :return: The raw bytes: [4-byte type][4-byte length][payload]
        """
        # Safety check
        if len(message_type) > 4:
            raise ValueError("message_type must be up to 4 characters.")
        # Pickle the object
        payload = pickle.dumps(obj)
        # Build the header
        header = message_type.encode('ascii')[:4].ljust(4, b' ')
        header += struct.pack('!I', len(payload))
        return header + payload

    @staticmethod
    def decode_header(header: bytes):
        """
        Extract the (message_type, payload_len) from an 8-byte header.
        """
        if len(header) < HEADER_SIZE:
            raise ValueError(f"Header must be at least {HEADER_SIZE} bytes.")
        message_type_bytes = header[:MESSAGE_TYPE_SIZE]
        payload_len_bytes = header[MESSAGE_TYPE_SIZE:]
        message_type = message_type_bytes.decode('ascii').strip()
        payload_len = struct.unpack('!I', payload_len_bytes)[0]
        return message_type, payload_len

    @staticmethod
    def decode_payload(payload: bytes):
        """
        Unpickle the payload to get the Python object.
        """
        return pickle.loads(payload)
