# acync_server_executor.py
import asyncio
import json
import time

# Import our new AsyncPickleServer
from PyServerManager.async_server.async_pickle_server import AsyncPickleServer
from PyServerManager.executors.task_executor import TaskExecutor


# Comment out the old SocketServer import
# from PyServerManager.server.server import SocketServer


class ServerExecutor(TaskExecutor):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Extract host and port from args
        self.port = self.args_dict.pop('port', 65535)
        self.host = self.args_dict.pop('host', '127.0.0.1')
        if self.port is None or self.host is None:
            raise Exception("Port and host must be specified")
        self.data_workers = self.args_dict.pop('data_workers', 4)
        self.cmd_workers = self.args_dict.pop('cmd_workers', 1)
        self.server: AsyncPickleServer = None

    def setup_server(self, data_workers=None, cmd_workers=None):
        data_workers = data_workers or self.data_workers
        cmd_workers = cmd_workers or self.cmd_workers
        self.logger.info(f"Creating AsyncPickleServer on {self.host}:{self.port} with {data_workers} workers")
        # loop = asyncio.new_event_loop()
        # Create the async server, passing in our data handler
        # We'll define a custom "on_data" method that does the equivalent of "live_run"
        self.server = AsyncPickleServer(
            host=self.host,
            port=self.port,
            data_handler=self.on_data_handler,  # define below
            data_workers=data_workers,  # or however many worker threads you want for CPU-bound tasks
            cmd_workers=cmd_workers,  # or however many worker threads you want for CPU-bound tasks
            logger=self.logger,
            worker_init_fn=self.worker_init_fn
        )
        # self.server.serve_forever(runner=None)
        # self.main_entry()

    def worker_init_fn(self):
        return None

    def setup_parser(self):
        super().setup_parser()

    def on_data_handler(self, payload):
        """
        This function is called whenever the server receives a "DATA" message.
        The 'payload' is the unpickled object from the client.

        Here we do the same logic as 'live_run' used to do, except we
        might not have explicit '*args, **kwargs'. Instead, we assume the client
        sent a dict, or we can handle any type.
        """
        self.logger.info(f"[on_data_handler] Received payload: {payload}")

        # Example "work" - let's replicate your old 'live_run' loop
        for i in range(10):
            time.sleep(0.1)  # This is CPU-bound, so it's run in a thread pool (not blocking the loop)
            print(f"Doing something {i + 1}...")

        data_to_return = {'test': f"Live run complete on port {self.port}!", 'img': payload}
        self.logger.info(f"Data to return: {data_to_return}")

        # Return a result object (the server will pickle and send it back to the client)
        return {"status": "OK", "msg": data_to_return}



def main():
    """
    Main entry point if running this script as `python acync_server_executor.py ...`.
    This is where we:
     1) Create the ServerExecutor
     2) Apply arguments from the base class (host, port, logger_level, etc.)
     3) setup_server() with the desired worker counts
     4) Finally, call `serve_forever()` to block until user hits Ctrl+C
    """
    executor = ServerExecutor()

    # The base class’s parser has run in `__init__` => we have `executor.args_dict`.
    # Retrieve any arguments we want.
    logger_level = int(executor.args_dict.get('logger_level', 20))
    open_in_new_terminal = bool(executor.args_dict.get('open_in_new_terminal', False))
    data_workers = int(executor.args_dict.get('data_workers', 4))
    cmd_workers = int(executor.args_dict.get('cmd_workers', 1))

    executor.logger.setLevel(logger_level)

    executor.logger.info("=== Starting server from main() in acync_server_executor ===")
    executor.logger.info(f" open_in_new_terminal = {open_in_new_terminal}")
    executor.logger.info(f" data_workers         = {data_workers}")
    executor.logger.info(f" cmd_workers          = {cmd_workers}")

    # Prepare the server
    executor.setup_server(data_workers=data_workers, cmd_workers=cmd_workers)

    print('Server should be running after serve_forever(). Press Ctrl+C to quit.')

    # serve_forever() will block until KeyboardInterrupt (Ctrl+C) or until
    # the server is shut down from a remote 'shutdown_server' command.
    try:
        executor.server.serve_forever(runner=None)
    except KeyboardInterrupt:
        print("KeyboardInterrupt detected. Stopping server...")
        # If we get here, `serve_forever` might already do a graceful shutdown,
        # but we can call it explicitly if we want.
        asyncio.run(executor.server.stop_server())
    print('Server script is now exiting.')


if __name__ == '__main__':
    executor = ServerExecutor()
    print(f"args_dict: {json.dumps(executor.args_dict, indent=2)}")
    lvl = executor.args_dict.get('logger_level', 20)
    data_workers = executor.args_dict.get('data_workers', 1)
    cmd_workers = executor.args_dict.get('cmd_workers', 1)
    executor.logger.setLevel(int(lvl))
    executor.setup_server(data_workers=data_workers, cmd_workers=cmd_workers)
    executor.server.serve_forever(runner=None)
    print('Server should be running. Press Ctrl+C to quit.')
    try:
        while executor.server.is_running:
            pass
    except KeyboardInterrupt:
        pass
    executor.server.stop_server()
    print('Server script is now exiting.')
