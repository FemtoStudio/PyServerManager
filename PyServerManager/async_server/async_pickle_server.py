import asyncio
import logging
import multiprocessing
import traceback
from multiprocessing import Process

from PyServerManager.async_server.base_async_pickle import BaseAsyncPickle
from PyServerManager.core.logger import SingletonLogger


def heavy_compute_example(payload):
    """
    Example CPU-bound function:
    Simulates a slow loop (10 x ~1.1s).
    """
    import time
    for i in range(10):
        time.sleep(1.1)
        print(f"...processing payload {i}...")
    return {"status": "OK", "processed": payload}


##################################
# Example Worker Functions
##################################

def worker_main_data(data_queue, result_queue, data_handler, worker_init_fn=None):
    """
    Worker process for 'DATA' messages.
    Continuously reads (client_id, payload) from data_queue,
    calls data_handler(payload), and puts (client_id, result) into result_queue.
    """
    if worker_init_fn is not None:
        # worker_init_fn might return something or just do in-place global init
        worker_init_fn()
    while True:
        try:
            client_id, payload = data_queue.get()  # blocks until data
            if client_id is None and payload is None:
                # sentinel => shutdown
                print("[worker_main_data] Received sentinel, shutting down...")
                break

            print(f"[worker_main_data] Processing payload for client {client_id}")
            result = data_handler(payload)
            result_queue.put((client_id, result))

        except Exception as e:
            print(f"[worker_main_data] Error: {e}\nTraceback: {traceback.extract_stack()}")


def worker_main_cmd(cmd_queue, result_queue):
    """
    Worker process for 'CMD' messages.
    If cmd_payload == "shutdown_server", we put (None, "__server_shutdown__") in the result queue
    to signal the server to shut down.
    Otherwise, we respond with "CMD processed: <payload>" to that client.
    """
    while True:
        try:
            client_id, cmd_payload = cmd_queue.get()  # blocks
            if client_id is None and cmd_payload is None:
                break

            if cmd_payload == "shutdown_server":
                result_queue.put((None, "__server_shutdown__"))
            else:
                # Default behavior: echo back a string
                result = f"CMD processed: {cmd_payload}"
                result_queue.put((client_id, result))

        except Exception as e:
            print(f"[worker_main_cmd] Error: {e}\nTraceback: {traceback.extract_stack()}")


##################################
# The AsyncPickleServer Implementation
##################################

class AsyncPickleServer(BaseAsyncPickle):
    """
    An asyncio-based server that uses separate queues for DATA vs CMD messages,
    plus a result queue to send back results to clients.

    The server spawns worker processes for data tasks and command tasks,
    so heavy computations won't block the main event loop.
    """

    def __init__(
            self,
            host='127.0.0.1',
            port=5050,
            logger=None,
            data_workers=2,
            cmd_workers=1,
            data_handler=None,
            worker_init_fn=None,
    ):
        """
        :param data_workers: Number of processes for handling DATA tasks
        :param cmd_workers: Number of processes for handling CMD tasks
        :param data_handler: The function used by data workers to process payload
        """
        self.host = host
        self.port = port
        self.logger = logger or SingletonLogger.get_instance("AsyncPickleServer")
        self.logger.setLevel(logging.INFO)

        self.server = None
        self._stopping = False

        # Instead of a single integer, store clients by peername => (reader, writer)
        self.clients = {}

        # Set up multiprocessing manager and queues
        self.mp_manager = multiprocessing.Manager()
        self.data_queue = self.mp_manager.Queue()
        self.cmd_queue = self.mp_manager.Queue()
        self.result_queue = self.mp_manager.Queue()

        # Set default or user-specified data handler
        self.data_handler = data_handler or heavy_compute_example
        self.worker_init_fn = worker_init_fn or (lambda: None)

        # Spawn worker processes for data
        self.data_processes = []
        self.logger.info(f"Starting {data_workers} data worker processes...")
        for _ in range(data_workers):
            p = Process(
                target=worker_main_data,
                args=(self.data_queue, self.result_queue, self.data_handler, self.worker_init_fn)
            )
            p.start()
            self.data_processes.append(p)

        # Spawn worker processes for cmd
        self.cmd_processes = []
        for _ in range(cmd_workers):
            p = Process(
                target=worker_main_cmd,
                args=(self.cmd_queue, self.result_queue)
            )
            p.start()
            self.cmd_processes.append(p)

    async def start_server(self):
        """
        Binds the socket and begins serving.
        We also create a background task to read from result_queue and respond to clients.
        """
        self.server = await asyncio.start_server(
            self.handle_client,
            self.host,
            self.port
        )
        self.logger.info(f"Server started on {self.host}:{self.port}")

        # Start the result listener in the background
        asyncio.create_task(self._result_listener())

        async with self.server:
            await self.server.serve_forever()

    async def stop_server(self, force_terminate_timeout=5.0):
        """
        Gracefully shuts down:
          1) Stop accepting connections.
          2) Send sentinel (None,None) to worker processes => signals them to exit.
          3) Close existing client connections.
          4) Join processes. If a process doesn't exit within `force_terminate_timeout` seconds, terminate it.
          5) Shut down the manager to free resources.
          6) Mark server as not running.
        """
        self._stopping = True
        self.logger.info("Stopping server...")

        # Stop accepting new connections
        if self.server is not None:
            self.server.close()
            await self.server.wait_closed()

        # === 1) Tell data workers to stop ===
        for _ in self.data_processes:
            self.data_queue.put((None, None))
        # Attempt to join them
        for p in self.data_processes:
            p.join(timeout=force_terminate_timeout)
            if p.is_alive():
                self.logger.warning(f"Data process {p.pid} still alive after join timeout; terminating.")
                p.terminate()

        # === 2) Tell cmd workers to stop ===
        for _ in self.cmd_processes:
            self.cmd_queue.put((None, None))
        # Attempt to join them
        for p in self.cmd_processes:
            p.join(timeout=force_terminate_timeout)
            if p.is_alive():
                self.logger.warning(f"CMD process {p.pid} still alive after join timeout; terminating.")
                p.terminate()

        # === 3) Close all active client connections ===
        for peername, (reader, writer) in list(self.clients.items()):
            writer.close()
            await writer.wait_closed()
            self.clients.pop(peername, None)

        # === 4) Shut down the multiprocessing.Manager ===
        self.mp_manager.shutdown()

        self.logger.info("Server has fully stopped.")

    async def handle_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        """
        Each new client connection is handled here.
        We'll read messages in a loop, route them to the appropriate queue,
        and rely on _result_listener to send responses back.

        Additionally, if we see a special command like 'get_server_info',
        we handle it here in the main thread (so we can access server state).
        """
        peername = writer.get_extra_info('peername')
        self.clients[peername] = (reader, writer)
        self.logger.info(f"New client connected from {peername}")

        try:
            while not self._stopping:
                msg = await self.read_next_message(reader)
                if msg is None:
                    self.logger.info(f"Client {peername} disconnected.")
                    break

                message_type, payload = msg
                self.logger.debug(f"[{peername}] type='{message_type}' payload={payload}")

                if message_type == "DATA":
                    # Put in the data queue => worker_main_data
                    self.data_queue.put((peername, payload))

                elif message_type == "CMD":
                    if payload == "get_server_info":
                        # Handle this command directly in the server
                        info = self.get_server_info()
                        await self.write_message(writer, "RESP", info)
                    else:
                        # Put in the cmd queue => worker_main_cmd
                        self.cmd_queue.put((peername, payload))

                else:
                    self.logger.warning(f"Unknown message_type '{message_type}' from {peername}")

        except asyncio.IncompleteReadError:
            self.logger.info(f"Client {peername} connection aborted.")
        except ConnectionResetError:
            self.logger.info(f"Client {peername} connection reset.")
        except Exception as e:
            self.logger.exception(f"Error in handle_client for {peername}: {e}")
        finally:
            # Cleanup
            writer.close()
            try:
                await writer.wait_closed()
            except ConnectionResetError:
                self.logger.warning(f"Client {peername} connection reset while closing.")
            self.clients.pop(peername, None)
            self.logger.info(f"Client {peername} closed.")

    async def _result_listener(self):
        """
        Background coroutine that reads (client_id, result) from result_queue
        and sends a 'RESP' message back to the correct client, if still connected.

        If we get (None, '__server_shutdown__'), we call stop_server().
        """
        self.logger.info("Result listener started.")
        loop = asyncio.get_running_loop()

        while not self._stopping:
            try:
                # run_in_executor => don't block the event loop
                client_id, result = await loop.run_in_executor(None, self.result_queue.get)

                # If worker_main_cmd asked for server shutdown:
                if client_id is None and result == "__server_shutdown__":
                    self.logger.info("[_result_listener] Received server shutdown request from worker.")
                    loop.create_task(self.stop_server())
                    continue

                # If we got a weird sentinel
                if client_id is None:
                    continue

                self.logger.debug(f"[_result_listener] Received result for {client_id}: {result}")

                # Respond to the client, if they still exist
                if client_id in self.clients:
                    _, writer = self.clients[client_id]
                    await self.write_message(writer, "RESP", result)
                else:
                    self.logger.warning(f"Client {client_id} not connected, dropping result.")

            except Exception as e:
                self.logger.exception(f"Error in _result_listener: {e}")

        self.logger.info("Result listener exiting.")

    def serve_forever(self, runner=None, force_terminate_timeout=5.0):
        """
        A convenience method that starts the server with runner.run()
        and blocks until Ctrl+C or stop_server is invoked.
        """
        runner = runner or asyncio

        async def _start_server_flow():
            try:
                await self.start_server()
            except asyncio.CancelledError:
                pass
            finally:
                # If the server was canceled or ended, ensure we shut it down
                await self.stop_server(force_terminate_timeout=force_terminate_timeout)

        try:
            runner.run(_start_server_flow())
        except KeyboardInterrupt:
            print("Keyboard interrupt, exiting.")

    @property
    def is_running(self) -> bool:
        """
        Return True if the server is bound and we have not yet initiated stopping.
        """
        return (self.server is not None) and (not self._stopping)

    def get_server_info(self) -> dict:
        """
        Return a dictionary of current server status:
         - host/port
         - how many data/cmd workers
         - how many clients connected
         - list of client peernames
         - queue sizes
         - whether server is stopping or still running
        """
        try:
            data_queue_size = self.data_queue.qsize()
        except NotImplementedError:
            data_queue_size = "unknown"

        try:
            cmd_queue_size = self.cmd_queue.qsize()
        except NotImplementedError:
            cmd_queue_size = "unknown"

        try:
            result_queue_size = self.result_queue.qsize()
        except NotImplementedError:
            result_queue_size = "unknown"

        return {
            "host": self.host,
            "port": self.port,
            "data_workers_count": len(self.data_processes),
            "cmd_workers_count": len(self.cmd_processes),
            "connected_clients_count": len(self.clients),
            "connected_clients_peernames": [str(k) for k in self.clients.keys()],
            "data_queue_size": data_queue_size,
            "cmd_queue_size": cmd_queue_size,
            "result_queue_size": result_queue_size,
            "is_stopping": self._stopping,
            "is_running": self.is_running
        }


if __name__ == '__main__':
    import asyncio

    # A quick demo usage
    server = AsyncPickleServer(
        host='127.0.0.1',
        port=12355,  # or any free port
        data_workers=2,
        cmd_workers=1
    )
    server.serve_forever()
