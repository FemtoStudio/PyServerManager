# server_executor.py
import time

from core.logger import logger, dict_to_string
from executors.task_executor import TaskExecutor
from server.server import SocketServer

class ServerExecutor(TaskExecutor):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.port = self.args_dict.pop('port', SocketServer.find_available_port())
        self.host = self.args_dict.pop('host', '127.0.0.1')
        self.server = SocketServer(port=self.port, data_handler=self.live_run, host=self.host)
        self.server.start_accepting_clients(return_response_data=True)
        self.logger.info(f"Server started on port {self.server.host}:{self.server.port}")

    def setup_parser(self):
        super().setup_parser()

    def live_run(self, *args, **kwargs):
        self.logger.info(f'[live_run] Port: {self.port}')
        self.logger.info(f'kwargs: {kwargs}{dict_to_string(kwargs)}')
        self.logger.info(f'args: {args}')

        # Example "work"
        for i in range(10):
            time.sleep(0.1)
            print(f'Doing something {i + 1}...')

        data_to_return = f'Live run complete {self.port}'
        self.logger.info(f'Data to return: {data_to_return}')
        return data_to_return


if __name__ == '__main__':
    executor = ServerExecutor()
    # Optionally adjust logger level
    # lvl = executor.args_dict.get('logger_level', 20)
    # executor.logger.setLevel(int(lvl))
    print('Server should be running. Press Ctrl+C to quit.')

    # Keep the script alive as long as the server is active
    try:
        while executor.server.active:
            pass
    except KeyboardInterrupt:
        pass

    # Once we break out of the loop, we can safely shut down
    executor.server.close_server()
    print('Server script is now exiting.')
