#!/usr/bin/env python
"""
Server System for Handling Client and Management Connections

This module implements a server system with separate components for managing
client and management connections. It is designed to handle multiple clients concurrently
and allows administrative tasks through a management interface.

## Components:
- **SocketServer**: The central server class that initializes and manages the entire server's operation.
- **ConnectionAcceptor**: Handles incoming connections by accepting them and spawning threads for each.
- **BaseConnectionHandler**: An abstract class defining a common interface for handling connections.
- **ClientConnectionHandler**: A subclass of BaseConnectionHandler for handling client-specific data.
- **ManagementConnectionHandler**: A subclass of BaseConnectionHandler for handling management commands.

## Data Flow:
1. **Client Connection and Data Processing:**
   - Clients connect to the server via the client port.
   - `ConnectionAcceptor` accepts the connection and creates a `ClientConnectionHandler` instance.
   - The handler receives data from the client, processes it, and enqueues the request for worker threads to handle.
   - Worker threads process the request and send responses if necessary.

2. **Management Commands:**
   - A management client (like a ServerManager GUI) connects to the management port.
   - `ManagementConnectionHandler` is responsible for receiving and processing commands such as `get_status`, `disconnect_client`, or `shutdown_server`.
   - These commands are processed, and the relevant actions are taken (e.g., sending status data, disconnecting a client, shutting down the server).

## Threading Model:
- **ConnectionAcceptor**: Runs its own thread to accept connections.
- **ConnectionHandler subclasses**: Each client or management connection runs in its own thread.
- **Worker Threads**: A pool of worker threads is used to process requests from clients concurrently.

## Synchronization:
Thread-safe data structures like `queue.Queue` are used to ensure thread-safe operation, allowing for concurrent data reception and processing without blocking other threads.
"""

import pickle
import queue
import socket
import threading

from .base import ServerClientBase
from .utils import MessageReceiver, SingletonMeta


class BaseConnectionHandler:
    """
    Abstract base class for handling connections.

    This class defines a common interface for connection handlers, including shared attributes
    and methods for handling connections. It requires subclasses to implement the `run` method.

    Attributes:
        server (SocketServer): Reference to the main server instance.
        conn (socket): The socket object representing the connection.
        addr (tuple): The address of the connected client or management client.
        logger (Logger): Logger for logging connection events.
        receiver (MessageReceiver): Object to handle incoming messages.
    """
    def __init__(self, server, conn, addr):
        """
        Initializes a new connection handler.

        @param server: The server instance managing the connection.
        @param conn: The socket object for the connection.
        @param addr: The address of the connection.
        """
        self.server = server
        self.conn = conn
        self.addr = addr
        self.logger = server.logger
        self.receiver = MessageReceiver()

    def run(self):
        """
        Starts the connection handler.

        This method must be implemented by subclasses.
        @raise NotImplementedError: If not implemented by the subclass.
        """
        raise NotImplementedError("Subclasses should implement this method.")

    def close_connection(self):
        """
        Closes the connection and logs the event.
        """
        try:
            self.conn.close()
            self.logger.debug(f"Connection with {self.addr} closed.")
        except Exception as e:
            self.logger.error(f"Error closing connection with {self.addr}: {e}")


class ClientConnectionHandler(BaseConnectionHandler):
    """
    Handles individual client connections by receiving data and enqueuing requests for processing.

    This class is responsible for managing the lifecycle of a client connection,
    from receiving data to enqueuing requests for worker threads to process.

    Attributes:
        server (SocketServer): Reference to the main server instance.
        conn (socket): The socket object representing the connection.
        addr (tuple): The address of the connected client.
        logger (Logger): Logger for logging connection events.
        receiver (MessageReceiver): Object to handle incoming messages.
    """
    def run(self):
        """
        Starts the client connection handler, receives data, and enqueues requests for processing.

        This method continuously receives data from the client, processes it, and enqueues
        the request into the server's `request_queue` for worker threads to handle.
        """
        self.logger.debug(f"Handling client connection from {self.addr}.")
        self.server.client_connections[self.addr] = {'conn': self.conn, 'status': 'Connected'}
        try:
            while True:
                data = self.conn.recv(4096)
                if not data:
                    self.logger.debug(f"No data received from {self.addr}, closing connection.")
                    break

                self.server.client_connections[self.addr]['status'] = 'Receiving Data'
                messages = self.receiver.feed_data(data)
                for message_type, payload in messages:
                    # Enqueue the request
                    request_info = {
                        'conn': self.conn,
                        'addr': self.addr,
                        'message_type': message_type,
                        'payload': payload,
                        'data_handler': self.server.data_handler,
                        'return_response_data': self.server.return_response_data,
                    }
                    self.server.client_connections[self.addr]['status'] = 'Processing Request'
                    self.server.request_queue.put(request_info)
        except ConnectionResetError:
            self.logger.warning(f"Connection reset by {self.addr}.")
        except OSError as e:
            if e.errno == 10053:
                self.logger.warning(f"Connection aborted by {self.addr}.")
            else:
                self.logger.error(f"OSError occurred: {e}")

        except Exception as e:
            self.logger.error(f"An unexpected error occurred: {e}")
        finally:
            self.server.close_connection(self.addr)


class ManagementConnectionHandler(BaseConnectionHandler):
    """
    Handles management connections and processes administrative commands.

    This class is responsible for handling management connections from the ServerManager GUI.
    It processes commands such as `get_status`, `disconnect_client`, and `shutdown_server`.

    Attributes:
        server (SocketServer): Reference to the main server instance.
        conn (socket): The socket object representing the connection.
        addr (tuple): The address of the connected management client.
        logger (Logger): Logger for logging connection events.
        receiver (MessageReceiver): Object to handle incoming messages.
    """
    def run(self):
        """
        Starts the management connection handler, receives commands, and performs administrative actions.

        This method continuously receives management commands, processes them, and performs
        actions such as querying the server status, disconnecting clients, or shutting down the server.
        """
        self.logger.debug(f"Handling management connection from {self.addr}.")
        try:
            while True:
                data = self.conn.recv(4096)
                if not data:
                    self.logger.debug(f"No data received from management client {self.addr}, closing connection.")
                    break
                messages = self.receiver.feed_data(data)
                for message_type, payload in messages:
                    if message_type == 'MNGC':
                        try:
                            command_data = pickle.loads(payload)
                            command = command_data.get('command')
                            if command == 'get_status':
                                # Prepare status data
                                clients = [{'addr': str(addr), 'status': info['status']}
                                           for addr, info in self.server.client_connections.items()]
                                request_queue_length = len([c for c in clients if c['status'] == 'Processing Request'])
                                status = {
                                    'clients': clients,
                                    'queue_length': request_queue_length
                                }
                                # Encode the status data
                                encoded_status = self.server.encode_data('STAT', status)
                                self.conn.sendall(encoded_status)
                            elif command == 'disconnect_client':
                                target_addr = tuple(command_data.get('target_addr'))
                                if target_addr in self.server.client_connections:
                                    self.server.close_connection(target_addr)
                                    self.logger.info(f"Disconnected client {target_addr}")
                                else:
                                    self.logger.warning(f"Client {target_addr} not found")
                            elif command == 'shutdown_server':
                                self.server.close_server()
                            else:
                                self.logger.error(f"Unknown management command: {command}")
                        except Exception as e:
                            self.logger.error(f"Error handling management command: {e}")
                    else:
                        self.logger.error(f"Unknown message type in management interface: {message_type}")
        except ConnectionResetError:
            self.logger.warning(f"Management connection reset by {self.addr}.")
        except OSError as e:
            if e.errno == 10053:
                self.logger.warning(f"Management connection aborted by {self.addr}.")
            else:
                self.logger.error(f"OSError occurred in management connection: {e}")
        except Exception as e:
            self.logger.error(f"An unexpected error occurred in management connection: {e}")
        finally:
            self.close_connection()


class ConnectionAcceptor:
    """
    Manages the acceptance of incoming connections and spawns handler threads.

    This class listens on a specified socket for incoming connections, accepts them,
    and spawns a new thread for each connection using a handler class (e.g., ClientConnectionHandler or ManagementConnectionHandler).

    Attributes:
        host (str): The hostname or IP address to bind the socket.
        port (int): The port number to bind the socket.
        handler_class (type): The class to handle each accepted connection.
        server (SocketServer): Reference to the main server instance.
        name (str): A descriptive name for logging purposes.
        socket (socket): The socket object bound to the specified host and port.
        active (bool): A flag indicating whether the acceptor is running.
        accept_thread (Thread): The thread that runs `accept_connections`.
    """
    def __init__(self, host, port, handler_class, server, name="ConnectionAcceptor"):
        """
        Initializes the connection acceptor.

        @param host: The host on which to listen for connections.
        @param port: The port on which to listen for connections.
        @param handler_class: The handler class to handle the connections.
        @param server: The server instance managing the acceptor.
        @param name: Optional name for the acceptor, used for logging.
        """
        self.host = host
        self.port = port
        self.handler_class = handler_class
        self.server = server
        self.logger = server.logger
        self.name = name

        # Initialize socket
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.socket.bind((self.host, self.port))
        self.socket.listen(1)
        self.active = True

        self.accept_thread = threading.Thread(target=self.accept_connections)
        self.accept_thread.daemon = True
        self.accept_thread.start()
        self.logger.info(f"{self.name} listening on {self.host}:{self.port}")

    def accept_connections(self):
        """
        Continuously accepts new connections and spawns handler threads.

        This method runs in a loop while `self.active` is True. For each accepted
        connection, it creates an instance of `self.handler_class` and starts a new thread to run the handler.
        """
        self.logger.debug(f"{self.name} is accepting connections on {self.host}:{self.port}.")
        while self.active:
            try:
                conn, addr = self.socket.accept()
                self.logger.debug(f"{self.name} accepted connection from {addr}.")
                handler = self.handler_class(self.server, conn, addr)
                thread = threading.Thread(target=handler.run)
                thread.daemon = True
                thread.start()
            except OSError as e:
                if not self.active:
                    self.logger.info(f"{self.name} is shutting down.")
                else:
                    self.logger.error(f"{self.name} error accepting connections: {e}")

    def stop(self):
        """
          Stops the connection acceptor by closing the socket.
        """
        self.active = False
        try:
            self.socket.close()
            self.logger.info(f"{self.name} socket closed.")
        except Exception as e:
            self.logger.error(f"{self.name} error closing socket: {e}")

    def join(self):
        """
        Waits for the acceptor thread to finish.
        """
        self.accept_thread.join()


class SocketServer(ServerClientBase, metaclass=SingletonMeta):
    """
    The main server class responsible for managing client and management connections.

    This class initializes the server by creating connection acceptors for client and management
    connections, and starts worker threads to process incoming requests.

    Attributes:
        server_ready (bool): Indicates if the server is ready to accept connections.
        active (bool): Flag to control the server's active state.
        data_handler (function): A function to process incoming client data.
        return_response_data (bool): Flag to indicate if responses should be sent back to clients.
        host (str): The hostname or IP address the server is bound to.
        request_queue (Queue): A thread-safe queue holding incoming client requests.
        worker_threads (list): List of worker threads processing client requests.
        client_connections (dict): Tracks active client connections with {addr: conn}.
        port (int): The port number for client connections.
        management_port (int): The port number for management connections.
    """
    @classmethod
    def get_instances(cls):
        """
        Returns a copy of all server instances.

        @return: Copy of server instances.
        @rtype: dict
        """
        return cls._instances.copy()

    def __init__(self, port=None, data_handler=None, host="localhost", management_port=None):
        """
        Initializes the socket server, sets up connection acceptors, and starts worker threads.

        @param port: Optional port for client connections. A port will be chosen if None is provided.
        @param data_handler: Optional data handler for processing incoming client data.
        @param host: The host on which the server is running.
        @param management_port: Optional port for management connections.
        """
        super().__init__()
        self.server_ready = False
        self.active = True
        self.data_handler = data_handler
        self.return_response_data = True  # Moved from method argument to attribute
        self.host = host

        # Initialize request queue and worker threads
        self.request_queue = queue.Queue()
        self.num_worker_threads = 4  # Adjust the number of worker threads as needed
        self.worker_threads = []
        self.client_connections = {}  # To keep track of client connections

        # Create connection acceptors
        self.port = port or self.find_available_port()
        self.client_acceptor = ConnectionAcceptor(
            host=self.host,
            port=self.port,
            handler_class=ClientConnectionHandler,
            server=self,
            name="ClientAcceptor"
        )

        self.management_port = management_port or (self.port + 1)
        self.management_acceptor = ConnectionAcceptor(
            host=self.host,
            port=self.management_port,
            handler_class=ManagementConnectionHandler,
            server=self,
            name="ManagementAcceptor"
        )

        handler_logger = f', DataHandler:{data_handler.__name__}' if data_handler else ''
        self.logger.info(f"Server created on port {self.port}, Host:{host}{handler_logger}")
        self.logger.info(f"Management interface available on port {self.management_port}")

    def start_accepting_clients(self, data_handler=None, return_response_data=False):
        """
        Starts accepting client connections and processing requests.

        This method sets up the server to begin accepting clients by assigning
        the data handler, initializing response flags, and starting the worker threads.

        @param data_handler: Function to handle incoming client data (optional).
        @param return_response_data: Flag to determine if responses should be sent back to clients.
        """
        self.logger.info(f"Server starting on port {self.port}")
        self.data_handler = data_handler or self.data_handler
        self.return_response_data = return_response_data

        # Start worker threads
        for _ in range(self.num_worker_threads):
            worker = threading.Thread(target=self.process_requests)
            worker.daemon = True
            worker.start()
            self.worker_threads.append(worker)

        self.server_ready = True


    def send_to_all_clients(self, data):
        """
        Sends a message to all connected clients.

        @param data: The data to be sent to clients.
        """
        encoded_data = self.encode_data('DATA', data)
        for addr, conn in self.client_connections.items():
            try:
                conn.sendall(encoded_data)
                self.logger.info(f"Data sent to client at {addr}")
            except Exception as e:
                self.logger.error(f"Failed to send data to client at {addr}: {e}")

    def close_connection(self, addr):
        """
        Closes a client connection and removes it from active connections.

        @param addr: The address of the client whose connection is to be closed.
        """
        self.logger.debug(f"Closing connection with {addr}")
        # Close the connection if it exists
        client_info = self.client_connections.pop(addr, None)
        if client_info:
            connection = client_info['conn']
            try:
                connection.close()
                self.logger.info(f"Closed connection for {addr}")
            except Exception as e:
                self.logger.error(f"Failed to close connection for {addr}: {e}")
        else:
            self.logger.debug(f"No connection found for {addr}")

    def close_server(self):
        """
        Closes the server, stops all acceptors, and closes all active connections.
        """
        self.active = False
        self.logger.info("Initiating server shutdown...")

        # Stop acceptors
        self.client_acceptor.stop()
        self.management_acceptor.stop()

        # Close client connections
        client_addrs = list(self.client_connections.keys())
        for addr in client_addrs:
            self.close_connection(addr)

        # Wait for acceptor threads to finish
        self.client_acceptor.join()
        self.management_acceptor.join()

        self.server_ready = False
        self.client_connections.clear()
        self.logger.info("Server has been fully shut down.")

    def process_requests(self):
        """
        Continuously processes requests from the request queue.

        Worker threads execute this method in a loop. It retrieves requests from the queue
        and processes them based on the message type (e.g., `DATA`, `CMD`). If required,
        responses are generated and sent back to clients.
        """
        while self.active:
            try:
                request_info = self.request_queue.get()
                conn = request_info['conn']
                addr = request_info['addr']
                message_type = request_info['message_type']
                payload = request_info['payload']
                data_handler = request_info['data_handler']
                return_response_data = request_info['return_response_data']

                with self.client_connections_lock:
                    self.client_connections[addr]['status'] = 'Processing Request'

                if message_type == 'DATA':
                    decoded_data = pickle.loads(payload)
                    if data_handler:
                        response = data_handler(decoded_data)
                        if response is not None and return_response_data:
                            encoded_response = self.encode_data('DATA', response)
                            try:
                                conn.sendall(encoded_response)
                            except Exception as e:
                                self.logger.error(f"Failed to send data to client at {addr}: {e}")
                elif message_type == 'CMD':
                    command = pickle.loads(payload)  # Correctly unpickle the payload
                    if command == 'quit':
                        self.close_server()
                        return
                    elif command == 'is_server_ready':
                        response = 'yes' if self.server_ready else 'no'
                        encoded_response = self.encode_data('RESP', response)
                        try:
                            conn.sendall(encoded_response)
                        except Exception as e:
                            self.logger.error(f"Failed to send response to client at {addr}: {e}")
                else:
                    self.logger.error(f"Unknown message type: {message_type}")

                self.client_connections[addr]['status'] = 'Idle'
                self.request_queue.task_done()
            except Exception as e:
                self.logger.error(f"Error processing request: {e}")

    def receive_data(self, conn, addr, data_handler=None, return_response_data=False):
        self.logger.debug(f"Inside receive_data for {addr}.")
        self.logger.debug(f"return_response_data:{return_response_data}, data_handler:{data_handler}")
        receiver = MessageReceiver()
        while True:
            try:
                data = conn.recv(4096)
                if not data:
                    self.logger.debug(f"No data received from {addr}, closing connection.")
                    break
                messages = receiver.feed_data(data)
                for message_type, payload in messages:
                    # Enqueue the request
                    request_info = {
                        'conn': conn,
                        'addr': addr,
                        'message_type': message_type,
                        'payload': payload,
                        'data_handler': data_handler,
                        'return_response_data': return_response_data,
                    }
                    self.request_queue.put(request_info)
            except ConnectionResetError:
                self.logger.warning(f"Connection reset by {addr}.")
                break
            except OSError as e:
                if e.errno == 10053:
                    self.logger.warning(f"Connection aborted by {addr}.")
                    break
                else:
                    self.logger.error(f"OSError occurred: {e}")
                    break
            except Exception as e:
                self.logger.error(f"An unexpected error occurred: {e}")
                break
        self.close_connection(addr)
