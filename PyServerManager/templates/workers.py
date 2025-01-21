import typing

from PySide6 import QtCore, QtWidgets

from PyServerManager.core.logger import SingletonLogger
from PyServerManager.templates.base_user_server_executor import BaseUserServerExecutor

logger = SingletonLogger.get_instance("ServerControlWidgetLogger")


class ServerInfoWorker(QtCore.QThread):
    """
    A QThread that calls server_exec.get_server_info() exactly once,
    then emits resultReady(dict) when done.
    """
    resultReady = QtCore.Signal(dict)

    def __init__(self, server_exec: BaseUserServerExecutor, parent: QtWidgets.QWidget = None):
        super().__init__(parent)
        self.server_exec = server_exec

    def run(self):
        info = self.server_exec.get_server_info()
        if info is None:
            info = {}
        self.resultReady.emit(info)


class ServerRequestWorker(QtCore.QThread):
    """
    Simple QThread for sending data to the server.
    """
    resultReady = QtCore.Signal(object)
    finished = QtCore.Signal()

    def __init__(
            self,
            server_exec: BaseUserServerExecutor,
            data_to_send: typing.Any,
            parent: typing.Optional[QtWidgets.QWidget] = None
    ):
        super().__init__(parent)
        self.server_exec = server_exec
        self.data_to_send = data_to_send

    def run(self):
        try:
            response = self.server_exec.send_data_to_server(self.data_to_send)
            self.resultReady.emit(response)
        except Exception as e:
            logger.error(f"ServerRequestWorker encountered an error: {e}", exc_info=True)
            self.resultReady.emit(None)
        finally:
            self.finished.emit()
