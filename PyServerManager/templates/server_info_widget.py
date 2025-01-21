# server_info_widget.py

import json
from PySide6 import QtCore, QtWidgets

from PyServerManager.templates.base_user_server_executor import BaseUserServerExecutor
from PyServerManager.core.logger import SingletonLogger
from PyServerManager.templates.workers import ServerInfoWorker

logger = SingletonLogger.get_instance("ServerInfoWidgetLogger")


class ServerInfoWidget(QtWidgets.QWidget):
    """
    Periodically queries the server for info and displays it in labels for
    numeric fields and a QTreeWidget for connected client list.
    The interval (in seconds) can be set via set_refresh_interval().
    """

    def __init__(
        self,
        server_exec: BaseUserServerExecutor,
        refresh_interval: float = 5.0,
        parent: QtWidgets.QWidget = None
    ):
        super().__init__(parent)
        self.server_exec = server_exec
        self.refresh_interval = refresh_interval
        self._worker = None

        self._setup_ui()
        self._setup_timer()

    def _setup_ui(self):
        main_layout = QtWidgets.QVBoxLayout(self)
        self.setLayout(main_layout)

        # Title
        label_title = QtWidgets.QLabel("<b>Server Info</b>")
        main_layout.addWidget(label_title)

        # (A) Create a QFormLayout for the numeric/string fields
        form_frame = QtWidgets.QFrame()
        form_layout = QtWidgets.QFormLayout(form_frame)
        main_layout.addWidget(form_frame)

        # We'll store references to QLabels so we can update them easily
        self.lbl_host = QtWidgets.QLabel("N/A")
        self.lbl_port = QtWidgets.QLabel("N/A")
        self.lbl_data_workers = QtWidgets.QLabel("0")
        self.lbl_cmd_workers = QtWidgets.QLabel("0")
        self.lbl_clients_count = QtWidgets.QLabel("0")
        self.lbl_data_queue = QtWidgets.QLabel("0")
        self.lbl_cmd_queue = QtWidgets.QLabel("0")
        self.lbl_result_queue = QtWidgets.QLabel("0")
        self.lbl_is_running = QtWidgets.QLabel("?")

        form_layout.addRow("Host:", self.lbl_host)
        form_layout.addRow("Port:", self.lbl_port)
        form_layout.addRow("Data Workers:", self.lbl_data_workers)
        form_layout.addRow("CMD Workers:", self.lbl_cmd_workers)
        form_layout.addRow("Clients Count:", self.lbl_clients_count)
        form_layout.addRow("Data Queue Size:", self.lbl_data_queue)
        form_layout.addRow("CMD Queue Size:", self.lbl_cmd_queue)
        form_layout.addRow("Result Queue Size:", self.lbl_result_queue)
        form_layout.addRow("Server Running?:", self.lbl_is_running)

        # (B) A QTreeWidget for the connected_clients_peernames
        self.tree_clients = QtWidgets.QTreeWidget()
        self.tree_clients.setHeaderLabels(["Connected Clients"])
        self.tree_clients.setColumnCount(1)
        main_layout.addWidget(self.tree_clients)

        # (C) A button to "Refresh now"
        self.btn_refresh = QtWidgets.QPushButton("Refresh Now")
        self.btn_refresh.clicked.connect(self.refresh_once)
        main_layout.addWidget(self.btn_refresh)

        main_layout.addStretch()

    def _setup_timer(self):
        """
        We create a QTimer to periodically fetch server info.
        """
        self.timer = QtCore.QTimer(self)
        self.timer.setInterval(int(self.refresh_interval * 1000))  # convert seconds to ms
        self.timer.timeout.connect(self.refresh_once)
        self.timer.start()

    def refresh_once(self):
        """
        Manually or automatically triggered to fetch server info once.
        We'll create a worker to avoid blocking the UI.
        """
        if not self.server_exec.client or not self.server_exec.client.is_connected:
            # logger.warning("Not connected to server; skipping get_server_info.")
            return

        # If there's a worker still alive, skip
        if self._worker and self._worker.isRunning():
            # logger.info("Previous worker still running, skipping this round.")
            return

        self._worker = ServerInfoWorker(self.server_exec, parent=self)
        self._worker.resultReady.connect(self.handle_info_result)
        # Approach A fix: handle finished => set self._worker = None
        self._worker.finished.connect(self.handle_info_finished)
        self._worker.start()

    def handle_info_finished(self):
        if self._worker:
            self._worker.deleteLater()
            self._worker = None

    def handle_info_result(self, info: dict):
        """
        Called once the worker finishes retrieving the info. We update the UI.
        info might look like:
        {
          "host": "127.0.0.1",
          "port": 5050,
          "data_workers_count": 2,
          "cmd_workers_count": 1,
          "connected_clients_count": 0,
          "connected_clients_peernames": [],
          "data_queue_size": 0,
          "cmd_queue_size": 0,
          "result_queue_size": 0,
          "is_stopping": false,
          "is_running": true
        }
        """
        logger.debug(f"handle_info_result => {info}")

        # (A) Update the labels
        self.lbl_host.setText(str(info.get("host", "N/A")))
        self.lbl_port.setText(str(info.get("port", "N/A")))
        self.lbl_data_workers.setText(str(info.get("data_workers_count", 0)))
        self.lbl_cmd_workers.setText(str(info.get("cmd_workers_count", 0)))
        self.lbl_clients_count.setText(str(info.get("connected_clients_count", 0)))
        self.lbl_data_queue.setText(str(info.get("data_queue_size", "N/A")))
        self.lbl_cmd_queue.setText(str(info.get("cmd_queue_size", "N/A")))
        self.lbl_result_queue.setText(str(info.get("result_queue_size", "N/A")))
        self.lbl_is_running.setText(str(info.get("is_running", False)))

        # (B) Populate the tree with connected client peernames
        self.tree_clients.clear()
        client_list = info.get("connected_clients_peernames", [])
        for client_name in client_list:
            item = QtWidgets.QTreeWidgetItem([client_name])
            self.tree_clients.addTopLevelItem(item)

    def set_refresh_interval(self, seconds: float):
        """
        Allows adjusting the timer interval at runtime.
        """
        self.refresh_interval = seconds
        if self.timer:
            self.timer.setInterval(int(seconds * 1000))

    def stop_timer(self):
        if self.timer:
            self.timer.stop()

    def start_timer(self):
        if self.timer:
            self.timer.start()
