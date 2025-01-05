import asyncio
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

        self.logger.info(f"Creating AsyncPickleServer on {self.host}:{self.port}")

        # Create the async server, passing in our data handler
        # We'll define a custom "on_data" method that does the equivalent of "live_run"
        self.server = AsyncPickleServer(
            host=self.host,
            port=self.port,
            data_handler=self.on_data_handler,  # define below
            data_workers=4,  # or however many worker threads you want for CPU-bound tasks
            logger=self.logger,
        )

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

    async def run_async(self):
        """
        An async method that starts the server and runs forever (until stopped).
        """
        self.logger.info("Starting AsyncPickleServer... (awaiting start_server)")
        await self.server.start_server()  # This will block (async) until server is stopped.

    async def shutdown_async(self):
        """
        Gracefully stop the server.
        """
        await self.server.stop_server()

    def main_entry(self):
        """
        This replaces the old "if __name__ == '__main__'" block's logic.
        We'll run our event loop here.
        """
        print("Server should be running. Press Ctrl+C to quit.")
        try:
            # Run the async entry
            asyncio.run(self.run_async())
        except asyncio.exceptions.CancelledError:
            print("server cancelled, shutting down server.")
        except KeyboardInterrupt:
            print("KeyboardInterrupt detected, shutting down server.")
            # We can do another run to close down
            try:
                asyncio.run(self.shutdown_async())
            except RuntimeError:
                pass
        print("Server script is now exiting.")


if __name__ == '__main__':
    # Create the executor
    kwargs = {'port': AsyncPickleServer.find_available_port(), 'host': 'localhost'}
    executor = ServerExecutor(kwargs)
    executor.args_dict = kwargs
    # Optionally adjust logger level
    # lvl = executor.args_dict.get('logger_level', 20)
    # executor.logger.setLevel(int(lvl))

    # Now call the main_entry, which runs our asyncio loop
    executor.main_entry()
