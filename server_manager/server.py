# server.py
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

import json
import os
import pickle
import queue
import socket
import threading
import time

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

    def cleanup_resources(self):
        """
        Performs cleanup of resources held by the connection handler.
        """
        self.close_connection()

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
            while self.server.active:
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
        self.handler_threads = []

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

    def join_handler_threads(self):
        for thread in self.handler_threads:
            try:
                thread.join()
            except Exception as e:
                self.logger.debug(f"thread errored while joining {e}")

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

    def __init__(self, port=None, data_handler=None, host="localhost", management_port=None, server_register_dir=None):
        """
        Initializes the socket server, sets up connection acceptors, and starts worker threads.

        @param port: Optional port for client connections. A port will be chosen if None is provided.
        @param data_handler: Optional data handler for processing incoming client data.
        @param host: The host on which the server is running.
        @param management_port: Optional port for management connections.
        @param server_register_dir: Optional dir to the JSON file for server registry.

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
        # Handle JSON file path for server registry

        self.server_register_dir = server_register_dir

        self.registry_lock = threading.RLock()  # Lock for thread-safe registry access

        # Register the server in the JSON file
        self.register_server()

        self.cleanup_thread = threading.Thread(target=self.periodic_cleanup, name="RegistryCleanupThread")
        self.cleanup_thread.daemon = True
        self.cleanup_thread.start()


        self.shutdown_event = threading.Event()
        self.shutdown_thread = threading.Thread(target=self.shutdown_watcher, name="ShutdownWatcher")
        self.shutdown_thread.start()

    def shutdown_watcher(self):
        """
        Waits for the shutdown event and calls close_server().
        """
        self.shutdown_event.wait()  # Block until the event is set
        self.close_server()

    def periodic_cleanup(self, interval=3600):
        """
        Periodically cleans up the server registry every 'interval' seconds.
        """
        self.cleanup_server_registry()
        sleep_interval = 1  # Sleep in 1-second intervals
        elapsed_time = 0
        while self.active:
            time.sleep(sleep_interval)
            elapsed_time += sleep_interval
            if elapsed_time >= interval:
                self.cleanup_server_registry()
                elapsed_time = 0

    @property
    def json_file_path(self):
        json_name = '.PyServer'
        if self.server_register_dir and os.path.isdir(self.server_register_dir):
            return os.path.join(self.server_register_dir, json_name)
        return os.path.expanduser(f'~/{json_name}')


    def register_server(self):
        """
        Registers the server in the JSON file.

        Adds an entry with the hostname as the key and a dictionary containing the port and
        data handler function name as the value.
        """
        server_key = f"{self.host}:{self.port}"
        data_handler_name = self.data_handler.__name__ if self.data_handler else None
        data_handler_info = f"{self.data_handler.__module__}.{self.data_handler.__qualname__}" if self.data_handler else None
        server_entry = {
            "hostname": self.host,
            "port": self.port,
            "data_handler": data_handler_name,
            "data_handler_info": data_handler_info
        }

        with self.registry_lock:
            registry = self.read_server_registry()
            registry[server_key] = server_entry
            self.write_server_registry(registry)
            self.logger.info(f"Server registered in {self.json_file_path}")

    def is_server_reachable(self, hostname, port, timeout=2.0):
        """
        Attempts to connect to a server to check if it is reachable.

        @param hostname: The hostname of the server.
        @param port: The port number of the server.
        @param timeout: Connection timeout in seconds.
        @return: True if the server is reachable, False otherwise.
        """
        try:
            with socket.create_connection((hostname, port), timeout=timeout):
                return True
        except (socket.timeout, ConnectionRefusedError, OSError) as e:
            self.logger.debug(f"Server {hostname}:{port} is not reachable: {e}")
            return False

    def cleanup_server_registry(self):
        """
        Cleans up the server registry by removing entries for servers that are not reachable.
        """
        server_registry_path = self.json_file_path
        self.logger.info(f"Cleaning up server registry at {server_registry_path}")

        with self.registry_lock:
            try:
                registry = self.read_server_registry()
                updated_registry = {}
                for server_key, server_entry in registry.items():
                    hostname = server_entry.get('hostname')
                    port = server_entry.get('port')
                    if self.is_server_reachable(hostname, port):
                        updated_registry[server_key] = server_entry
                    else:
                        self.logger.info(f"Removing unreachable server {server_key} from registry.")
                self.write_server_registry(updated_registry)
                self.logger.info("Server registry cleanup completed.")
            except Exception as e:
                self.logger.error(f"Error during server registry cleanup: {e}")

    def unregister_server(self):
        """
        Removes the server's entry from the JSON file.
        """

        server_key = f"{self.host}:{self.port}"
        self.logger.info(
            f"[{threading.current_thread().name}] Unregistering server from {self.json_file_path}, server_key: {server_key}")
        with self.registry_lock:
            self.logger.debug(f"[{threading.current_thread().name}] Acquired registry_lock.")
            registry = self.read_server_registry()
            self.logger.debug(f"[{threading.current_thread().name}] Registry contents: {registry}")
            if server_key in registry:
                del registry[server_key]
                self.write_server_registry(registry)
                self.logger.info(f"Server unregistered from {self.json_file_path}")
            else:
                self.logger.warning(f"Server key {server_key} not found in registry.")

    def read_server_registry(self):
        """
        Reads the server registry from the JSON file.

        @return: A dictionary representing the server registry.
        @rtype: dict
        """
        try:
            if os.path.exists(self.json_file_path):
                with open(self.json_file_path, 'r') as json_file:
                    registry = json.load(json_file)
                    self.logger.debug(f"Registry read successfully: {registry}")
            else:
                registry = {}
                self.logger.debug("Registry file does not exist. Starting with empty registry.")
            return registry
        except Exception as e:
            self.logger.error(f"Error reading server registry: {e}")
            return {}

    def write_server_registry(self, registry):
        """
        Writes the server registry to the JSON file.

        @param registry: The server registry to write.
        @type registry: dict
        """
        try:
            with open(self.json_file_path, 'w') as json_file:
                json.dump(registry, json_file, indent=4)
                self.logger.debug(f"Registry written successfully: {registry}")
        except Exception as e:
            self.logger.error(f"Error writing server registry: {e}")

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
            # worker.daemon = True
            worker.start()
            self.worker_threads.append(worker)

        self.server_ready = True
        # self.register_server()

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
        self.active = False
        self.logger.info("Initiating server shutdown...")

        # Unregister the server
        self.unregister_server()

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

        # Wait for handler threads to finish
        self.client_acceptor.join_handler_threads()
        self.management_acceptor.join_handler_threads()

        # Wait for worker threads to finish
        current_thread = threading.current_thread()
        for worker in self.worker_threads:
            if worker is not current_thread:
                try:
                    worker.join()
                except Exception as e:
                    self.logger.error(f"Error while joining worker thread: {e}")
            else:
                self.logger.debug(f"Skipping join on current thread: {worker.name}")

        # No need to join the shutdown thread as it will exit after calling close_server

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
        while self.active or not self.request_queue.empty():
            try:
                request_info = self.request_queue.get(timeout=1)  # Add a timeout here
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
                        self.logger.info("Shutdown command received.")
                        self.shutdown_event.set()
                        self.active = False  # Signal other worker threads to exit
                        # Optionally send a response to the client
                        response = 'Server is shutting down'
                        encoded_response = self.encode_data('RESP', response)
                        try:
                            conn.sendall(encoded_response)
                        except Exception as e:
                            self.logger.error(f"Failed to send response to client at {addr}: {e}")
                        return  # Exit this worker thread
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
            except queue.Empty:
                if not self.active:
                    break  # Exit the loop if the server is not active
                continue  # Continue if active but queue is empty
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
