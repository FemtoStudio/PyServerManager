# PyServerManager

**PyServerManager** is an open-source Python toolkit for orchestrating, controlling, and monitoring server connections. It supports both command-line and GUI-driven workflows, making it easy to run a server, manage connected clients, and handle administrative tasks such as disconnecting clients or shutting down the server.

---

## Key Features

- **Multi-Threaded Server**  
  A robust multi-threaded architecture powers `SocketServer`, enabling parallel processing of connected clients without blocking other operations.

- **Flexible Client Management**  
  A dedicated client module (`client.py`) connects to the server, handles data exchange, and gracefully disconnects if needed.

- **Real-Time GUI**  
  A PySide6-based GUI (`server_manager.py`) allows you to monitor connected clients, track queue length, and issue commands (disconnect/shutdown).

- **CLI Entrypoints**  
  A command-line interface (`entrypoints.py`) lets you launch the server in the background or start the GUI to manage a remote/local server.

- **Task Execution & Scripting**  
  `execute_manager.py` and the `executors/` directory allow you to run Python scripts in a controlled manner, with inline or separate-terminal execution. Scripts (e.g., `some_script.py`) can be encoded/decoded for structured argument passing.

- **Logging & Extensibility**  
  A customizable logger system (`logger.py`) offers colored output, multi-level logging, and optional progress bars if `tqdm` is available.

- **Easy Test Integration**  
  The `tests/` folder includes examples of orchestrating integration tests, verifying GUI functionality, and validating server/client behavior.

---

## Module Hierarchy

Below is a high-level view of the repository:

```plaintext
PyServerManager/
├── cli/
│   └── entrypoints.py            # CLI entrypoints for server / GUI
├── core/
│   ├── test_scripts/
│   │   └── some_script.py        # Example script for ExecuteThreadManager
│   ├── __init__.py
│   ├── execute_manager.py        # Orchestration for running scripts/tasks
│   └── logger.py                 # Logging logic
├── executors/
│   ├── __init__.py
│   ├── server_executor.py        # Example server executor using TaskExecutor
│   └── task_executor.py          # Base class for tasks that parse arguments, run, send structured output
├── server/
│   ├── __init__.py
│   ├── base.py                   # Base server/client classes
│   ├── client.py                 # Client that connects to SocketServer
│   ├── server.py                 # Main SocketServer with management + client acceptance
│   ├── server_manager.py         # PySide6 GUI for management
│   └── utils.py                  # Utilities (MessageReceiver, SingletonMeta, etc.)
├── tests/
│   ├── orchestrates/
│   │   ├── client_runner.py
│   │   ├── integration_test.py
│   │   └── server_runner.py
│   ├── test_gui/
│   │   └── test_gui.py
│   ├── __init__.py
│   ├── test_01.py
│   ├── test_02.py
│   ├── test_client.py
│   └── test_server.py
├── __init__.py
└── README.md                     # Project documentation
```

---

## Installation

1. **Clone the Repository**  
   ```bash
   git clone https://github.com/your-username/PyServerManager.git
   cd PyServerManager
   ```
2. **Install Requirements**  
   Make sure you have Python 3.8+ installed, then install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
3. **Optional**: If you want to use the GUI, install PySide6:
   ```bash
   pip install PySide6
   ```

---

## Basic Usage

### 1. Launch the Server via CLI

```bash
pyservermanager server --host localhost --port 5050 --management-port 5051
```
- Starts the server on host `localhost`, listening for client connections on `5050` and management commands on `5051`.

### 2. Launch the GUI

```bash
pyservermanager gui --host localhost --port 5051
```
- Opens the PySide6 GUI, allowing you to view connected clients, queue length, and send admin commands (disconnect/shutdown).

### 3. Connect a Client

Use `SocketClient` (from within Python) or write your own script:
```python
from server.client import SocketClient

client = SocketClient(host="localhost", port=5050)
client.connect_to_server()
response = client.attempt_to_send({"cmd": "test"})
print("Server response:", response)
client.disconnect_from_server()
```

---

## Architecture Overview

1. **Server**  
   The `SocketServer` runs continuously, accepting client connections on the main port and management connections on a separate management port. It also spins up worker threads to process client requests in parallel.

2. **Client**  
   A `SocketClient` instance connects to the server, sends data/commands, and handles responses. Connection attempts can be retried on a loop if desired.

3. **Management GUI**  
   `ServerManager` (PySide6) polls the management port for server status updates and issues commands (e.g., `get_status`, `disconnect_client`, `shutdown_server`).

4. **Task/Script Execution**  
   `ExecuteThreadManager` handles launching Python scripts (like `some_script.py`) in either inline mode (capturing output) or new terminal windows. Arguments can be passed as base64-encoded JSON for safe serialization.

---

## Contributing

Contributions are welcome! To propose changes or add features:

1. **Fork the Repository**  
2. **Create a Branch** (e.g., `feature/your-feature`)  
3. **Commit Changes**: `git commit -m "Add awesome new feature"`  
4. **Push to Branch**: `git push origin feature/your-feature`  
5. **Create Pull Request** in GitHub

---

## License

This project is licensed under the MIT License. See [LICENSE](LICENSE) for more details.

---

## Contact

For any questions or issues, feel free to open an issue or reach out to us on GitHub.  

---

## Acknowledgments

Special thanks to all contributors who help improve **PyServerManager** with every commit and pull request!

