"""
Server Manager GUI for Monitoring and Managing Server Status

This module implements a GUI-based server management tool using PySide6 for monitoring
connected clients and queue status, as well as issuing administrative commands such as
disconnecting clients or shutting down the server.

## Components:
- **StatusUpdateThread**: A QThread-based class that handles communication with the server
  for retrieving status updates and sending commands to the server.
- **ServerManager**: A Qt MainWindow class that provides a GUI for the server manager, allowing
  users to view connected clients, monitor the queue length, and issue server management commands.

## Data Flow:
1. **Status Updates**:
   - The `StatusUpdateThread` sends periodic requests to the server to retrieve the current
     status, including the list of connected clients and queue length.
   - Upon receiving the status data, it emits a signal (`status_updated`) to update the GUI.

2. **Client Management**:
   - The GUI allows the user to select a client from the list and disconnect it by sending a
     command to the server.

3. **Server Shutdown**:
   - The user can issue a shutdown command from the GUI, which is sent to the server to
     gracefully stop its operation.

## Threading Model:
- **StatusUpdateThread**: Runs in a separate thread to handle network communication without
  blocking the main GUI thread.
"""


import pickle
import socket
import struct
import sys

from PySide6 import QtWidgets, QtCore

from utils import MessageReceiver, safe_eval


class StatusUpdateThread(QtCore.QThread):
    """
    A QThread subclass responsible for communicating with the server and updating status.

    This thread connects to the management port of the server and sends periodic requests
    to retrieve the current status, including the list of connected clients and queue length.

    Attributes:
        host (str): The server's host address.
        port (int): The management port of the server.
        is_connected (bool): Indicates if the thread is connected to the server.
        management_socket (socket): The socket used for communication with the server.
        receiver (MessageReceiver): A utility class for receiving and parsing incoming messages.
        running (bool): Controls whether the thread should keep running.
    """
    status_updated = QtCore.Signal(dict)
    """
    Signal emitted when the server status is updated.

    The signal carries a dictionary containing the server status information:
    - 'clients': A list of connected client addresses.
    - 'queue_length': The length of the server's request queue.
    """
    def __init__(self, host, port):
        super().__init__()
        self.host = host
        self.port = port
        self.is_connected = False
        self.management_socket = None
        self.receiver = MessageReceiver()
        self.running = True

    def run(self):
        """
        Main thread loop for sending status requests and receiving updates.

        This method attempts to connect to the server and periodically sends
        'get_status' commands to retrieve the current server status. The updates
        are emitted via the `status_updated` signal.
        """
        try:
            self.management_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.management_socket.connect((self.host, self.port))
            self.management_socket.settimeout(1.0)
            self.is_connected = True
            print(f"Connected to server at {self.host}:{self.port}")
        except Exception as e:
            print(f"Failed to connect to server: {e}")
            self.is_connected = False
            self.running = False
            return

        while self.running:
            try:
                # Send command to get server status
                command_data = {'command': 'get_status'}
                encoded_command = self.encode_data('MNGC', command_data)
                self.management_socket.sendall(encoded_command)

                # Receive response
                data = self.management_socket.recv(4096)
                if data:
                    messages = self.receiver.feed_data(data)
                    for message_type, payload in messages:
                        if message_type == 'STAT':
                            status = pickle.loads(payload)
                            # Emit signal with status
                            self.status_updated.emit(status)
                        else:
                            print(f"Unexpected message type: {message_type}")
                else:
                    print("No data received from server.")
                # Sleep before next update
                self.msleep(1000)  # Sleep for 1 second
            except socket.timeout:
                continue
            except Exception as e:
                print(f"Error in status update thread: {e}")
                break

        self.management_socket.close()
        self.is_connected = False

    def stop(self):
        """
          Stops the status update thread and closes the socket.
          """
        self.running = False

    def encode_data(self, message_type, data):
        """
        Encodes the message type and data into a byte stream for sending to the server.

        @param message_type: A 4-character string representing the message type.
        @param data: The data to be serialized and sent.
        @return: A byte stream containing the encoded message.
        @rtype: bytes
        """
        serialized_data = pickle.dumps(data)
        payload_length = len(serialized_data)
        header = message_type.encode('ascii')[:4].ljust(4, b' ')
        header += struct.pack('!I', payload_length)
        return header + serialized_data


class ServerManager(QtWidgets.QMainWindow):
    """
    Main window for the Server Manager GUI.

    This class provides a graphical interface for connecting to the server, viewing
    connected clients, monitoring the request queue, and issuing administrative commands
    such as disconnecting clients or shutting down the server.

    Attributes:
        status_thread (StatusUpdateThread): The thread responsible for handling server
                                            communication and status updates.
        is_connected (bool): Indicates if the GUI is connected to the server.
    """
    def __init__(self):
        """
         Initializes the ServerManager window and sets up the UI elements.
         """
        super().__init__()

        self.setWindowTitle("Server Manager")

        # Main widget
        self.main_widget = QtWidgets.QWidget()
        self.setCentralWidget(self.main_widget)

        # Layouts
        self.main_layout = QtWidgets.QVBoxLayout()
        self.main_widget.setLayout(self.main_layout)

        # Connection settings
        self.connection_layout = QtWidgets.QHBoxLayout()
        self.host_label = QtWidgets.QLabel("Host:")
        self.host_input = QtWidgets.QLineEdit("localhost")
        self.port_label = QtWidgets.QLabel("Port:")
        self.port_input = QtWidgets.QLineEdit("5051")
        self.connect_button = QtWidgets.QPushButton("Connect")
        self.connection_layout.addWidget(self.host_label)
        self.connection_layout.addWidget(self.host_input)
        self.connection_layout.addWidget(self.port_label)
        self.connection_layout.addWidget(self.port_input)
        self.connection_layout.addWidget(self.connect_button)

        # Connected clients label and list
        self.clients_label = QtWidgets.QLabel("Connected Clients:")
        self.clients_list = QtWidgets.QTreeWidget()
        self.clients_list.setColumnCount(2)
        self.clients_list.setHeaderLabels(['Client', 'Status'])

        # Queue status label
        self.queue_label = QtWidgets.QLabel("Queue Status:")
        self.queue_info = QtWidgets.QLabel("Queue Length: 0")

        # Buttons
        self.buttons_layout = QtWidgets.QHBoxLayout()
        self.disconnect_client_button = QtWidgets.QPushButton("Disconnect Selected Client")
        self.shutdown_server_button = QtWidgets.QPushButton("Shutdown Server")

        self.buttons_layout.addWidget(self.disconnect_client_button)
        self.buttons_layout.addWidget(self.shutdown_server_button)

        # Add widgets to layout
        self.main_layout.addLayout(self.connection_layout)
        self.main_layout.addWidget(self.clients_label)
        self.main_layout.addWidget(self.clients_list)
        self.main_layout.addWidget(self.queue_label)
        self.main_layout.addWidget(self.queue_info)
        self.main_layout.addLayout(self.buttons_layout)

        # Connect buttons
        self.connect_button.clicked.connect(self.connect_to_server)
        self.disconnect_client_button.clicked.connect(self.disconnect_selected_client)
        self.shutdown_server_button.clicked.connect(self.shutdown_server)

        # Management client attributes
        self.status_thread = None
        self.is_connected = False

    def connect_to_server(self):
        """
        Establishes a connection to the server and starts the status update thread.

        Retrieves the host and port information from the input fields and attempts to
        connect to the server. If successful, the `StatusUpdateThread` is started to
        periodically retrieve server status.
        """
        host = self.host_input.text()
        port_text = self.port_input.text()
        try:
            port = int(port_text)
        except ValueError:
            QtWidgets.QMessageBox.warning(self, "Invalid Port", "Please enter a valid port number.")
            return

        if self.status_thread is not None and self.status_thread.isRunning():
            self.status_thread.stop()
            self.status_thread.wait()

        self.status_thread = StatusUpdateThread(host, port)
        self.status_thread.status_updated.connect(self.update_status)
        self.status_thread.finished.connect(self.status_thread_finished)
        self.status_thread.start()
        self.is_connected = True

    def update_status(self, status):
        """
        Updates the UI with the current server status.

        This method is called when the `status_updated` signal is emitted by the
        `StatusUpdateThread`. It updates the list of connected clients and the queue length.

        @param status: A dictionary containing the server status.
        @type status: dict
        """
        self.connected_clients = status['clients']
        self.queue_length = status['queue_length']

        # Update clients list without clearing it
        current_clients = {self.clients_list.topLevelItem(i).text(0): self.clients_list.topLevelItem(i)
                           for i in range(self.clients_list.topLevelItemCount())}

        for client_info in status['clients']:
            client_addr = client_info['addr']
            client_status = client_info['status']
            if client_addr in current_clients:
                # Update existing item
                item = current_clients[client_addr]
                item.setText(1, client_status)
            else:
                # Add new client
                item = QtWidgets.QTreeWidgetItem(self.clients_list)
                item.setText(0, client_addr)
                item.setText(1, client_status)

        # Remove clients that are no longer connected
        for client_addr in current_clients:
            if client_addr not in [client_info['addr'] for client_info in status['clients']]:
                index = self.clients_list.indexOfTopLevelItem(current_clients[client_addr])
                self.clients_list.takeTopLevelItem(index)

        # Update queue info
        self.queue_info.setText(f"Queue Length: {self.queue_length}")

    def status_thread_finished(self):
        """
        Handles the event when the status thread finishes, indicating disconnection.

        Displays a warning message to the user and updates the UI to reflect the
        disconnection status.
        """
        self.is_connected = False
        self.clients_list.clear()
        QtWidgets.QMessageBox.warning(self, "Disconnected", "Disconnected from server.")

    def disconnect_selected_client(self):
        """
        Sends a request to the server to disconnect the selected client.

        This method retrieves the selected client from the list and sends a 'disconnect_client'
        command to the server. If no client is selected, a warning message is displayed.
        """
        if not self.is_connected:
            QtWidgets.QMessageBox.warning(self, "Not Connected", "Not connected to server.")
            return
        selected_items = self.clients_list.selectedItems()
        if selected_items:
            client_addr = selected_items[0].text(0)
            # Convert client_addr string back to tuple safely
            try:
                # Assuming client_addr is in the format "('127.0.0.1', 12345)"
                client_addr_tuple = safe_eval(client_addr)
                # Send command to server to disconnect client
                command_data = {
                    'command': 'disconnect_client',
                    'target_addr': client_addr_tuple
                }
                encoded_command = self.encode_data('MNGC', command_data)
                self.status_thread.management_socket.sendall(encoded_command)
                QtWidgets.QMessageBox.information(self, "Disconnect Client", f"Disconnecting client: {client_addr}")
                print(f"Disconnecting client: {client_addr}")
            except Exception as e:
                QtWidgets.QMessageBox.warning(self, "Disconnect Client", f"Failed to disconnect client: {e}")
                print(f"Failed to disconnect client: {e}")
        else:
            QtWidgets.QMessageBox.warning(self, "Disconnect Client", "No client selected.")
            print("No client selected")

    def shutdown_server(self):
        """
        Sends a request to the server to shut down.

        Prompts the user for confirmation and, if confirmed, sends a 'shutdown_server' command
        to the server. The status thread is stopped after the server shuts down.
        """
        if not self.is_connected:
            QtWidgets.QMessageBox.warning(self, "Not Connected", "Not connected to server.")
            return

        # Send command to server to shut down
        reply = QtWidgets.QMessageBox.question(
            self, "Shutdown Server", "Are you sure you want to shut down the server?",
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No, QtWidgets.QMessageBox.No
        )
        if reply == QtWidgets.QMessageBox.Yes:
            try:
                command_data = {'command': 'shutdown_server'}
                encoded_command = self.encode_data('MNGC', command_data)
                self.status_thread.management_socket.sendall(encoded_command)
                print("Shutting down server")
                self.status_thread.stop()
                self.status_thread.wait()
                # self.close()
            except Exception as e:
                QtWidgets.QMessageBox.warning(self, "Shutdown Server", f"Failed to shut down server: {e}")
                print(f"Failed to shut down server: {e}")
        else:
            print("Server shutdown canceled")

    def encode_data(self, message_type, data):
        """
        Encodes the message type and data into a byte stream for sending to the server.

        @param message_type: A 4-character string representing the message type.
        @param data: The data to be serialized and sent.
        @return: A byte stream containing the encoded message.
        @rtype: bytes
        """
        serialized_data = pickle.dumps(data)
        payload_length = len(serialized_data)
        header = message_type.encode('ascii')[:4].ljust(4, b' ')
        header += struct.pack('!I', payload_length)
        return header + serialized_data

    def closeEvent(self, event):
        """
        Handles the event when the window is closed, ensuring the status thread is stopped.

        This method stops the status update thread and waits for it to finish before
        closing the application.
        """
        # Clean up the management socket
        if self.status_thread is not None:
            self.status_thread.stop()
            self.status_thread.wait()
        event.accept()


if __name__ == '__main__':
    app = QtWidgets.QApplication(sys.argv)
    manager = ServerManager()
    manager.show()
    sys.exit(app.exec())
