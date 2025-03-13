"""
server_control_widget.py

Example refactoring to:
 - Put advanced settings in a separate SettingsDialog
 - Load/store those settings automatically from ~/.PyServerManagerSettings/settings.json
 - Optionally override them with external calls to from_dict
 - On dialog accept => we save back the final user settings
"""

import json
import typing
from pathlib import Path

from PySide6 import QtCore, QtWidgets

from PyServerManager.async_server.base_async_pickle import BaseAsyncPickle
from PyServerManager.core.logger import SingletonLogger
from PyServerManager.templates.base_user_server_executor import BaseUserServerExecutor
from PyServerManager.templates.server_info_widget import ServerInfoWidget
from PyServerManager.templates.workers import ServerRequestWorker
from PyServerManager.widgets.collapsibleframe import CollapsibleFrame

logger = SingletonLogger.get_instance("ServerControlWidgetLogger")

# Define paths for user folder & settings file
USER_SETTINGS_FOLDER = Path.home()
USER_SETTINGS_FILE = USER_SETTINGS_FOLDER / ".PyServerManagerSettings"


def load_user_settings_file() -> dict:
    """
    Attempts to load JSON from ~/.PyServerManagerSettings/settings.json.
    Returns an empty dict if file not found or parse error.
    """
    if not USER_SETTINGS_FILE.is_file():
        return {}
    try:
        with USER_SETTINGS_FILE.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.warning(f"Failed to load user settings file: {USER_SETTINGS_FILE}\nError: {e}")
        return {}


def save_user_settings_file(settings: dict):
    """
    Saves 'settings' to ~/.PyServerManagerSettings/settings.json (JSON).
    Creates the folder if needed.
    """
    try:
        USER_SETTINGS_FOLDER.mkdir(parents=True, exist_ok=True)
        with USER_SETTINGS_FILE.open("w", encoding="utf-8") as f:
            json.dump(settings, f, indent=2)
    except Exception as e:
        logger.error(f"Failed to save user settings to {USER_SETTINGS_FILE}\nError: {e}")


class SettingsDialog(QtWidgets.QDialog):
    """
    A dialog containing server/client settings:
      - data_workers
      - cmd_workers
      - logger_level
      - open_in_new_terminal
      - auto_connect
      - start_sleep
      - retry_delay
      - max_retries

    On creation, tries to load from user folder if available.
    On accept, saves to user folder.

    Provides from_dict(...) and to_dict() for external usage as well.
    """

    def __init__(self, parent: typing.Optional[QtWidgets.QWidget] = None):
        super().__init__(parent)
        self.setWindowTitle("Server Settings")
        self.resize(350, 300)

        # Default internal settings
        self.internal_settings = {
            "data_workers": 2,
            "cmd_workers": 1,
            "logger_level": 20,
            "open_in_new_terminal": False,
            "auto_connect": False,
            "start_sleep": 2.0,
            "retry_delay": 2.0,
            "max_retries": 0
        }

        # Try to load user settings file
        file_settings = load_user_settings_file()
        # Merge into internal defaults
        self.internal_settings.update(file_settings)

        # Build the UI
        self._build_ui()

        # Now set the UI elements from self.internal_settings
        self.from_dict(self.internal_settings)

    def _build_ui(self):
        layout = QtWidgets.QVBoxLayout()
        self.setLayout(layout)

        form_layout = QtWidgets.QFormLayout()
        layout.addLayout(form_layout)

        # Data workers
        self.spin_data_workers = QtWidgets.QSpinBox()
        self.spin_data_workers.setRange(1, 64)
        form_layout.addRow("Data workers:", self.spin_data_workers)

        # Cmd workers
        self.spin_cmd_workers = QtWidgets.QSpinBox()
        self.spin_cmd_workers.setRange(0, 64)
        form_layout.addRow("CMD workers:", self.spin_cmd_workers)

        # Logger level
        self.combo_logger_level = QtWidgets.QComboBox()
        log_levels = [
            ("CRITICAL(50)", 50),
            ("ERROR(40)", 40),
            ("WARNING(30)", 30),
            ("INFO(20)", 20),
            ("DEBUG(10)", 10),
        ]
        for (text, val) in log_levels:
            self.combo_logger_level.addItem(text, userData=val)
        form_layout.addRow("Logger level:", self.combo_logger_level)

        # Open in new terminal
        self.check_open_terminal = QtWidgets.QCheckBox()
        form_layout.addRow("Open in new terminal:", self.check_open_terminal)

        # Auto-Connect
        self.check_auto_connect = QtWidgets.QCheckBox()
        form_layout.addRow("Auto-Connect client:", self.check_auto_connect)

        # Next, connect params (start_sleep, retry_delay, max_retries)
        self.spin_start_sleep = QtWidgets.QDoubleSpinBox()
        self.spin_start_sleep.setRange(0.0, 999.0)
        self.spin_start_sleep.setSingleStep(0.5)
        form_layout.addRow("Connect: start_sleep:", self.spin_start_sleep)

        self.spin_retry_delay = QtWidgets.QDoubleSpinBox()
        self.spin_retry_delay.setRange(0.0, 999.0)
        self.spin_retry_delay.setSingleStep(0.5)
        form_layout.addRow("Connect: retry_delay:", self.spin_retry_delay)

        self.spin_max_retries = QtWidgets.QSpinBox()
        self.spin_max_retries.setRange(0, 9999)
        form_layout.addRow("Connect: max_retries=0->None:", self.spin_max_retries)

        # Buttons (OK/Cancel)
        btn_box = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel,
            QtCore.Qt.Horizontal,
            self
        )
        btn_box.accepted.connect(self.accept)
        btn_box.rejected.connect(self.reject)
        layout.addWidget(btn_box)

    def from_dict(self, settings: dict):
        """
        Load UI from the given dict of settings keys.
        This updates the *UI elements* to reflect those values.
        """
        print("loading from settings", json.dumps(settings, indent=2))
        # If keys are missing, we keep defaults
        self.spin_data_workers.setValue(settings.get("data_workers", 2))
        self.spin_cmd_workers.setValue(settings.get("cmd_workers", 1))

        # find index in combo_logger_level for numeric log level
        log_val = settings.get("logger_level", 20)
        for i in range(self.combo_logger_level.count()):
            val = self.combo_logger_level.itemData(i)
            if val == log_val:
                self.combo_logger_level.setCurrentIndex(i)
                break

        self.check_open_terminal.setChecked(settings.get("open_in_new_terminal", False))
        self.check_auto_connect.setChecked(settings.get("auto_connect", False))

        self.spin_start_sleep.setValue(settings.get("start_sleep", 2.0))
        self.spin_retry_delay.setValue(settings.get("retry_delay", 2.0))
        self.spin_max_retries.setValue(settings.get("max_retries", 0))

    def to_dict(self) -> dict:
        """
        Return a dict of current UI values (the user-chosen settings).
        """
        log_val = self.combo_logger_level.currentData()
        return {
            "data_workers": self.spin_data_workers.value(),
            "cmd_workers": self.spin_cmd_workers.value(),
            "logger_level": log_val,
            "open_in_new_terminal": self.check_open_terminal.isChecked(),
            "auto_connect": self.check_auto_connect.isChecked(),
            "start_sleep": self.spin_start_sleep.value(),
            "retry_delay": self.spin_retry_delay.value(),
            "max_retries": self.spin_max_retries.value(),
        }

    def accept(self):
        """
        When user clicks OK, gather the final UI values and save them to file.
        """
        final_values = self.to_dict()
        logger.info(f"[SettingsDialog] Accept => final values: {final_values}")

        # Update our internal_settings
        self.internal_settings.update(final_values)

        # Save to user folder
        try:
            save_user_settings_file(final_values)
        except Exception as e:
            logger.error(f"Error saving settings: {e}")

        super().accept()  # close the dialog


# A small Unicode gear for Settings
SETTINGS_SYMBOL = u"\U00002699\ufe0f"  # ⚙️


class ServerControlWidget(QtWidgets.QWidget):
    serverStarted = QtCore.Signal(str, int)
    clientConnected = QtCore.Signal()
    serverResponse = QtCore.Signal(object)
    executeFinished = QtCore.Signal()

    def __init__(
            self,
            server_exec: BaseUserServerExecutor = None,
            parent: typing.Optional[QtWidgets.QWidget] = None
    ):
        super().__init__(parent=parent)

        self.server_exec = server_exec or BaseUserServerExecutor(logger=logger)
        self._server_running = False
        self._client_connected = False

        # Track if we are attempting to connect
        self._connect_in_progress = False

        # Dialog for advanced settings
        self.settings_dialog = SettingsDialog(parent=self)

        # Set up the UI
        self.setup_ui()

    def setup_ui(self):
        layout = QtWidgets.QVBoxLayout()
        self.setLayout(layout)

        # Host/Port row
        row_host_port = QtWidgets.QHBoxLayout()
        lbl_host = QtWidgets.QLabel("Host:")
        self.edit_host = QtWidgets.QLineEdit("127.0.0.1")
        lbl_port = QtWidgets.QLabel("Port:")
        self.spin_port = QtWidgets.QSpinBox()
        self.spin_port.setRange(1, 65535)
        self.spin_port.setValue(5050)

        # Button: Find Port
        self.btn_find_port = QtWidgets.QPushButton("Find Port")
        self.btn_find_port.clicked.connect(self.on_find_port)

        # Button: Settings (small gear icon)
        self.btn_open_settings = QtWidgets.QPushButton(SETTINGS_SYMBOL)
        # A little styling to make it narrower
        self.btn_open_settings.setFixedWidth(32)
        font = self.btn_open_settings.font()
        font.setPointSize(10)
        self.btn_open_settings.setFont(font)
        self.btn_open_settings.clicked.connect(self.on_open_settings)
        # Optionally disable the default border for a more "icon-like" look:
        # self.btn_open_settings.setStyleSheet("QPushButton { border: none; }")

        row_host_port.addWidget(lbl_host)
        row_host_port.addWidget(self.edit_host)
        row_host_port.addWidget(lbl_port)
        row_host_port.addWidget(self.spin_port)
        row_host_port.addWidget(self.btn_find_port)
        row_host_port.addWidget(self.btn_open_settings)
        layout.addLayout(row_host_port)

        # Collapsible "Server Info" panel
        self.info_widget = ServerInfoWidget(self.server_exec, refresh_interval=5.0, parent=self)
        info_collapsible = CollapsibleFrame("Server Info", self)
        info_collapsible.set_expanded(False)
        info_collapsible.add_widget(self.info_widget)
        layout.addWidget(info_collapsible)

        # Server + Client Controls
        self.btn_start_server = QtWidgets.QPushButton("Start Server")
        self.btn_start_server.clicked.connect(self.on_start_server)
        layout.addWidget(self.btn_start_server)

        # Row for "Connect" and "Cancel Connect" side by side
        row_connect = QtWidgets.QHBoxLayout()

        # Connect button, disabled until server is started
        self.btn_connect_client = QtWidgets.QPushButton("Connect to Server")
        self.btn_connect_client.setEnabled(False)  # disable by default
        self.btn_connect_client.clicked.connect(self.on_connect_client)
        row_connect.addWidget(self.btn_connect_client)

        # Cancel Connect button, also disabled by default
        self.btn_cancel_connect = QtWidgets.QPushButton("Cancel Connect")
        self.btn_cancel_connect.setEnabled(False)
        self.btn_cancel_connect.clicked.connect(self.on_cancel_connect)
        row_connect.addWidget(self.btn_cancel_connect)

        layout.addLayout(row_connect)

        # A button to copy the command that starts the server (disabled until we actually start)
        self.btn_copy_cmd = QtWidgets.QPushButton("Copy Server Cmd")
        self.btn_copy_cmd.setEnabled(False)
        self.btn_copy_cmd.clicked.connect(self.on_copy_cmd)
        layout.addWidget(self.btn_copy_cmd)

        # (Removed or commented out any "Execute" button here to follow your request)

        layout.addStretch()

    # -------------------------
    # from_dict / to_dict
    # -------------------------
    def from_dict(self, config: dict):
        """
        If needed, load host/port from an external dict,
        and optionally pass advanced settings to the SettingsDialog.
        """
        self.edit_host.setText(config.get("host", "127.0.0.1"))
        self.spin_port.setValue(config.get("port", 5050))

        advanced = config.get("settings", {})
        if advanced:
            # we call self.settings_dialog.from_dict to override
            self.settings_dialog.from_dict(advanced)

    def to_dict(self) -> dict:
        """
        Return the user’s host/port plus advanced settings from the dialog.
        """
        result = {
            "host": self.edit_host.text().strip(),
            "port": self.spin_port.value(),
            "settings": self.settings_dialog.to_dict()
        }
        return result

    # -------------------------
    # Handlers
    # -------------------------
    def on_find_port(self):
        port = BaseAsyncPickle.find_available_port()
        self.spin_port.setValue(port)

    def on_open_settings(self):
        """
        Show the modal dialog. If user hits OK, the dialog will have already
        saved the new settings to disk in accept().
        """
        current_settings = self.settings_dialog.to_dict()

        # Show the dialog
        if self.settings_dialog.exec() == QtWidgets.QDialog.Accepted:
            # The user clicked OK => self.settings_dialog.to_dict() is final
            adv = self.settings_dialog.to_dict()

            # Immediately apply the new refresh interval
            new_period = adv.get("server_info_period", 5.0)
            self.info_widget.set_refresh_interval(new_period)

    def on_start_server(self):
        if self._connect_in_progress:
            QtWidgets.QMessageBox.warning(
                self,
                "Connection in Progress",
                "Cannot start a new server while attempting to connect.\n"
                "Please cancel the connect attempt first."
            )
            return

        if self._server_running:
            QtWidgets.QMessageBox.warning(
                self,
                "Server Already Running",
                "Server is already running."
            )
            return

        host = self.edit_host.text().strip()
        port = self.spin_port.value()
        adv = self.settings_dialog.to_dict()

        dw = adv["data_workers"]
        cw = adv["cmd_workers"]
        lvl = adv["logger_level"]
        open_term = adv["open_in_new_terminal"]

        # Start the server (thread or external process)
        self.server_thread = self.server_exec.run_server(
            host=host,
            port=port,
            open_new_terminal=open_term,
            data_workers=dw,
            cmd_workers=cw,
            logger_level=lvl
        )
        if self.server_thread:
            self.btn_copy_cmd.setEnabled(True)

        self._server_running = True
        self.btn_start_server.setEnabled(False)
        # Now allow connect
        self.btn_connect_client.setEnabled(True)

        self.serverStarted.emit(host, port)

    def on_connect_client(self):
        if not self._server_running:
            logger.warning("Server not running, cannot connect.")
            return

        adv = self.settings_dialog.to_dict()
        st = adv["start_sleep"]
        rd = adv["retry_delay"]
        mr = adv["max_retries"]
        if mr == 0:
            mr = None

        self._connect_in_progress = True
        self.btn_cancel_connect.setEnabled(True)
        self.btn_connect_client.setEnabled(False)

        self.server_exec.host = self.edit_host.text().strip()
        self.server_exec.port = self.spin_port.value()

        logger.info(f"Connect client => host={self.server_exec.host}, "
                    f"port={self.server_exec.port}, start_sleep={st}, retry_delay={rd}, max_retries={mr}")
        self.server_exec.connect_client(start_sleep=st, retry_delay=rd, max_retries=mr)


    def on_cancel_connect(self):
        """
        User clicked 'Cancel Connect' while a background retry
        is in progress.
        """
        if not self._connect_in_progress:
            return

        self._connect_in_progress = False
        self.server_exec.cancel_connect_attempt()

        # Re-enable the 'Connect to Server' button
        self.btn_connect_client.setEnabled(True)
        self.btn_cancel_connect.setEnabled(False)

        logger.info("User canceled the connect attempt.")

    def on_execute_request(self):
        if not self._client_connected:
            logger.warning("No client connected. Cannot execute request.")
            return

        data_to_send = {"example": "Data from user."}
        self.btn_execute.setEnabled(False)

        self._worker = ServerRequestWorker(self.server_exec, data_to_send)
        self._worker.resultReady.connect(self.handle_server_response)
        self._worker.finished.connect(self.handle_finished)
        self._worker.start()

    def handle_server_response(self, response):
        logger.info(f"Got server response: {response}")
        self.serverResponse.emit(response)

        # If we were never "connected" before, or if you want to handle
        # the moment you know the server accepted a request:
        if not self._client_connected:
            self._client_connected = True
            self._connect_in_progress = False
            self.btn_cancel_connect.setEnabled(False)

    def handle_finished(self):
        self.btn_execute.setEnabled(True)
        self.executeFinished.emit()
        if getattr(self, "_worker", None):
            self._worker.deleteLater()
            self._worker = None

    def on_copy_cmd(self):
        if not hasattr(self, "server_thread") or not self.server_thread:
            QtWidgets.QMessageBox.information(self, "No Cmd", "No server command available yet.")
            return

        cmd_str = self.server_thread.cmd or ""
        if not cmd_str:
            QtWidgets.QMessageBox.information(self, "Empty Cmd", "Server command string is empty.")
            return

        # Copy to clipboard
        clipboard = QtWidgets.QApplication.clipboard()
        clipboard.setText(cmd_str)

        QtWidgets.QMessageBox.information(
            self,
            "Command Copied",
            "The server command has been copied to your clipboard."
        )


if __name__ == "__main__":
    import sys

    app = QtWidgets.QApplication(sys.argv)

    widget = ServerControlWidget()
    widget.show()


    def on_server_started(h, p):
        print(f"[DEMO] Server started at {h}:{p}")


    def on_client_connected():
        print("[DEMO] Client connected!")


    def on_server_response(resp):
        print(f"[DEMO] Received response: {resp}")


    def on_execute_finished():
        print("[DEMO] Execute request finished.")


    widget.serverStarted.connect(on_server_started)
    widget.clientConnected.connect(on_client_connected)
    widget.serverResponse.connect(on_server_response)
    widget.executeFinished.connect(on_execute_finished)

    sys.exit(app.exec())
