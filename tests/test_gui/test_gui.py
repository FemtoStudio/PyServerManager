import os
import sys

# Adjust these imports based on your actual structure
# 1) For launching the server:
from PyServerManager.core.execute_manager import ExecuteThreadManager
# 2) For your client to connect to the server:
from PyServerManager.server.client import SocketClient
# PySide6 imports
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout,
    QHBoxLayout, QLineEdit, QPushButton, QTextEdit
)

HOST = '127.0.0.1'
PORT = SocketClient.find_available_port()


class ServerGUI(QMainWindow):
    """
    A simple PySide6 GUI that:
      - Connects to a running server
      - Has a text input for a message
      - A "Send" button
      - A log view to show sent messages
    """

    def __init__(self, host=HOST, port=PORT, parent=None):
        super().__init__(parent)

        self.setWindowTitle("PyServerManager - Test GUI")
        self.resize(500, 300)

        # -- Layout / UI Setup --
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout()
        central_widget.setLayout(main_layout)

        # A text area to display logs
        self.log_view = QTextEdit()
        self.log_view.setReadOnly(True)
        main_layout.addWidget(self.log_view)

        # A horizontal layout for the input + send button
        input_layout = QHBoxLayout()
        self.message_input = QLineEdit()
        self.message_input.setPlaceholderText("Type a message to send to the server...")
        input_layout.addWidget(self.message_input)

        self.send_button = QPushButton("Send")
        input_layout.addWidget(self.send_button)

        main_layout.addLayout(input_layout)

        # -- Socket Client Setup --
        self.host = host
        self.port = port
        self.client = SocketClient(host=self.host, port=self.port)

        # Attempt to connect right away
        self.client.attempting_to_connect(start_sleep=2)

        # Connect signals
        self.send_button.clicked.connect(self.on_send_clicked)

    def on_send_clicked(self):
        """
        Triggered when the user presses the 'Send' button.
        Sends the message to the server and logs it in the GUI.
        """
        msg = self.message_input.text().strip()
        if not msg:
            return  # ignore empty messages

        # Clear the input
        self.message_input.clear()

        # Attempt to send the message to the server
        try:
            # For example, let's assume the server expects some kind of "DATA" message
            # or maybe you just want to send a string. Adapt as needed:
            response = self.client.attempt_to_send({"type": "chat", "msg": msg})

            # The server might or might not respond; for now, just log the sent message
            self.log_view.append(f"[CLIENT -> SERVER]: {msg}")

        except Exception as e:
            self.log_view.append(f"[ERROR] Could not send message: {e}")


def launch_server_via_execute_manager():
    """
    Launch the server on a new thread using ExecuteThreadManager.
    Adapt 'python_exe' and 'script_path' to your actual server script.

    Example server script might be something like:
    PyServerManager/executors/server_executor.py (or similar)

    Returns the thread object if you need to manage it.
    """
    # Example: assume your server script is "PyServerManager/executors/server_executor.py"
    # and that it starts up a server listening on 127.0.0.1:5050
    # Adjust these paths and arguments to match your actual environment:

    python_exe = sys.executable  # or an explicit path
    script_path = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "..", 'PyServerManager', "executors", "server_executor.py")
    )

    manager = ExecuteThreadManager(
        python_exe=python_exe,
        script_path=script_path,
        export_env={},
        custom_activation_script=None,
        callback=None,  # or a global callback if you want
        custom_logger=None
    )

    # Create a thread to run the server script inline
    # If your server script expects command-line arguments, pass them in 'args={}'
    server_thread = manager.get_thread(args={'host': HOST, 'port': PORT}, open_new_terminal=True)
    server_thread.start()
    return server_thread


def main():
    # 1) Launch the server on a separate thread
    server_thread = launch_server_via_execute_manager()

    # 2) Create and show the GUI
    app = QApplication(sys.argv)
    # If your server listens on 127.0.0.1:5050 by default, do:
    gui = ServerGUI(host=HOST, port=PORT)
    gui.show()

    # 3) Run the Qt event loop
    exit_code = app.exec()

    # Optionally, if you want to kill the server after the GUI closes:
    # from PyServerManager.core.execute_manager import ExecuteThreadManager
    # manager.terminate_all()

    # Wait for server thread to exit (if it does)
    server_thread.join(timeout=5.0)

    sys.exit(exit_code)


if __name__ == "__main__":
    main()
