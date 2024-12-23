import time

import numpy as np

from server.client import SocketClient
client = SocketClient(host='127.0.0.1', port=62003)
client.attempting_to_connect()

# Prepare test data for multiple clients
num_clients = 5  # Adjust the number of clients as needed
test_data_list = [
    {
        'message': f'Hello from client {i}',
        'numbers': [i, i + 1, i + 2],
        'array': np.array([i * 10, i * 20, i * 30]),
        'value': i * 10
    }
    for i in range(num_clients)
]
clients = [SocketClient(host='127.0.0.1', port=62003) for i in range(num_clients)]
for i in range(num_clients):
    clients[i].attempt_to_send(
        test_data_list[i])

while True:
    time.sleep(1)

    pass
