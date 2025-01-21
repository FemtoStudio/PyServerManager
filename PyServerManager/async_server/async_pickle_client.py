# async_pickle_client.py

# async_pickle_client.py

import asyncio
import logging
import time
import traceback

from PyServerManager.async_server.base_async_pickle import BaseAsyncPickle


class AsyncPickleClient(BaseAsyncPickle):
    """
    An asyncio-based client that can attempt to connect in background,
    wait for connection, then send/receive messages in the same event loop.
    """

    def __init__(self, host='127.0.0.1', port=5050, logger=None):
        self.host = host
        self.port = port
        if logger:
            self.logger = logger
        # self.logger.setLevel(logging.INFO)

        self.reader = None
        self.writer = None

        # Are we currently connected?
        self.is_connected = False

        # If we want to stop retrying:
        self._stop_retrying = False

    async def connect_once(self):
        """
        Attempt to connect to self.host:self.port exactly once.
        On success, set is_connected = True, store self.reader, self.writer.
        On failure, raise the underlying exception.
        """
        self.logger.info(f"[connect_once] Attempting connect to {self.host}:{self.port}")
        self.reader, self.writer = await asyncio.open_connection(self.host, self.port)
        self.is_connected = True
        self.logger.info(f"[connect_once] Connected to server at {self.host}:{self.port}")

    async def background_retry_connect(
            self,
            start_sleep=2,
            retry_delay=2,
            max_retries=None
    ):
        """
        An async method that tries connect_once repeatedly until success or max_retries.
        If we succeed, we set is_connected=True. Otherwise, we eventually give up.
        """
        await asyncio.sleep(start_sleep)

        retries = 0
        while not self.is_connected and not self._stop_retrying:
            try:
                await self.connect_once()
            except ConnectionRefusedError as cre:
                self.logger.debug(f"[background_retry_connect] Connection refused: {cre}"
                                  f" (retrying in {retry_delay}s)")
            except Exception as e:
                self.logger.warning(f"[background_retry_connect] Connection failed: {e}")
                retries += 1
                if max_retries is not None and retries >= max_retries:
                    self.logger.warning("[background_retry_connect] Max retries reached. Stopping attempts.")
                    return
                await asyncio.sleep(retry_delay)
            else:
                self.logger.info("[background_retry_connect] Successfully connected!")
                break

        if not self.is_connected:
            self.logger.info("[background_retry_connect] Did not connect (or user stopped retry).")
        return True

    async def wait_for_connection(self, timeout=None):
        """
        Wait for is_connected to be True. If not connected after 'timeout', raise TimeoutError.
        If background_retry_connect is running, we eventually see if it succeeds.
        """
        if self.is_connected:
            return
        start_time = time.time()
        while not self.is_connected:
            await asyncio.sleep(0.2)
            if self._stop_retrying:
                break
            if timeout is not None and (time.time() - start_time) > timeout:
                raise TimeoutError("Timed out waiting for connection")
        if not self.is_connected:
            raise TimeoutError("Connection not established after wait_for_connection.")

    async def send_data(self, data):
        """
        Send a 'DATA' message; read the server's 'RESP'.
        Must be connected first (call wait_for_connection if needed).
        """
        if not self.is_connected:
            raise RuntimeError("Not connected. Call wait_for_connection or background_retry_connect first.")
        self.logger.debug(f"[send_data] Sending data: {data}")
        await self.write_message(self.writer, "DATA", data)
        msg = await self.read_next_message(self.reader)
        if msg:
            msg_type, payload = msg
            payload_print = payload[:100] + "..." if len(payload) > 100 else payload
            self.logger.debug(f"[send_data] Received {msg_type} => {payload_print}")
            return payload
        return None

    async def send_cmd(self, cmd):
        """
        Send a 'CMD' message; read the server's 'RESP'.
        """
        if not self.is_connected:
            raise RuntimeError("Not connected.")
        self.logger.info(f"[send_cmd] Sending command: {cmd}")
        await self.write_message(self.writer, "CMD", cmd)
        msg = await self.read_next_message(self.reader)
        if msg:
            msg_type, payload = msg
            self.logger.info(f"[send_cmd] Received {msg_type} => {payload}")
            return payload
        return None

    async def shutdown_server(self):
        """
        Send 'shutdown_server' command; return the server's response if any.
        """
        return await self.send_cmd("shutdown_server")

    async def close(self):
        """
        Close the connection if open, set is_connected=False.
        """
        if self.writer:
            self.writer.close()
            await self.writer.wait_closed()
        self.is_connected = False
        self._stop_retrying = True
        self.logger.info("[close] Connection closed.")

    def stop_retrying(self):
        """
        If background_retry_connect is in progress, signal it to stop.
        """
        self._stop_retrying = True


if __name__ == "__main__":
    import random


    # acync_server_executor
    async def run_one_data_client(client_label, host, port):
        """
        One sample client that:
          1) Connects
          2) Sends a 'DATA' message
          3) Prints server response
          4) Closes
        """
        logger = logging.getLogger(f"DataClient-{client_label}")
        client = AsyncPickleClient(host, port, logger)
        try:
            task = asyncio.create_task(client.background_retry_connect(start_sleep=1, retry_delay=2, max_retries=None))
            print(f"[{client_label}] => background_retry_connect started.")
            await asyncio.gather(task)
            data = {
                "client_label": client_label,
                "numbers": [random.randint(1, 100) for _ in range(3)],
                "message": f"Hello from {client_label}"
            }
            resp = await client.send_data(data)
            print(f"[{client_label}] => server responded with: {resp}")
        finally:
            await client.close()


    async def main():
        logging.basicConfig(level=logging.INFO)

        HOST = "127.0.0.1"
        PORT = 12345  # Must match the server's port

        # 1) Launch multiple data clients concurrently
        tasks = []
        for i in range(2):
            tasks.append(asyncio.create_task(run_one_data_client(f"client{i}", HOST, PORT)))
        await asyncio.gather(*tasks)

        print("All data clients finished. Now sending shutdown_server command...")

        # # 2) Send shutdown command
        shutdown_client = AsyncPickleClient(HOST, PORT, logging.getLogger("ShutdownClient"))
        try:
            await shutdown_client.connect_once()
            resp = await shutdown_client.shutdown_server()
            print(f"[ShutdownClient] => server responded with: {resp}")
        except Exception as e:
            print(f"[ShutdownClient] Could not connect or send shutdown: {e}")
            print(f"Traceback: {traceback.format_exc()}")
        finally:
            await shutdown_client.close()


    asyncio.run(main())
