
# PyServerManager

**PyServerManager** is an open-source Python tool designed for efficient monitoring and management of server connections, client queues, and administrative commands through an intuitive GUI interface. Built using PySide6, PyServerManager supports real-time updates, client management, and server shutdown functionality with a multi-threaded architecture for seamless performance.

---

## Features

- **Real-Time Monitoring**: View connected clients, monitor server queue status, and get live updates on server performance.
- **Client Management**: Easily disconnect clients and manage active connections.
- **Server Commands**: Issue commands to shut down the server and perform other administrative tasks directly from the GUI.
- **Multi-Threaded Support**: Ensures smooth communication with the server without blocking the GUI.

---

## Installation

1. **Clone the Repository:**

   ```bash
   git clone https://github.com/your-username/PyServerManager.git
   cd PyServerManager
   ```

2. **Install Requirements:**

   Make sure you have Python 3.8+ installed, then install dependencies:

   ```bash
   pip install -r requirements.txt
   ```

3. **Run PyServerManager:**

   ```bash
   python main.py
   ```

---

## Usage

1. **Server Setup**:
   - Start the `SocketServer` module on the server.
   - This will listen for client connections and management commands from **PyServerManager**.

2. **Starting the GUI**:
   - Run the `main.py` file to launch the GUI.
   - Use the interface to monitor server status, manage clients, and send administrative commands.

---

## Architecture

### Components

- **SocketServer**: Initializes and manages the main server operations, including handling multiple clients concurrently.
- **StatusUpdateThread**: A thread that communicates with the server to fetch real-time status updates for the GUI.
- **ServerManager (GUI)**: A PySide6-based GUI for managing clients and issuing server commands.

### Data Flow

1. **Client Connection**: Clients connect to `SocketServer`, which accepts connections and spawns a `ClientConnectionHandler` for each.
2. **Status Update**: The `StatusUpdateThread` regularly fetches data to update the GUI with the current server status.
3. **Commands**: Send commands (e.g., disconnect clients, shut down server) via the GUI.

---

## Contributing

We welcome contributions! Please follow these steps to contribute:

1. **Fork the Repository**
2. **Create a Branch**: `git checkout -b feature/YourFeature`
3. **Commit Changes**: `git commit -m 'Add new feature'`
4. **Push to Branch**: `git push origin feature/YourFeature`
5. **Create Pull Request**

---

## License

This project is licensed under the MIT License. See the [LICENSE](LICENSE) file for more details.

---

## Contact

For any questions or issues, feel free to open an issue or reach out to us via GitHub.

---

## Acknowledgments

Special thanks to all contributors for helping make **PyServerManager** better with each release!
