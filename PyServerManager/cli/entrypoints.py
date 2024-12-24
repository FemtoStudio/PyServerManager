# server_manager/entrypoints.py

import argparse
import sys


def launch_server(args):
    """
    Launch the server on the specified host and ports.
    """
    from server.server import SocketServer  # Import your server class
    import time

    # Create and start the server
    server = SocketServer(
        host=args.host,
        port=args.port,
        management_port=args.management_port
    )
    server.start_accepting_clients()  # Begin accepting connections
    print(f"Server running on {args.host}:{args.port} (management port: {args.management_port})")

    try:
        while server.active:
            time.sleep(1)
    except KeyboardInterrupt:
        print("KeyboardInterrupt detected, shutting down server.")
    finally:
        server.close_server()
        print("Server has been shut down.")


def launch_gui(args):
    """
    Launch the PySide6 GUI to manage the server.
    """
    import sys
    from PySide6.QtWidgets import QApplication
    from server.server_manager import ServerManager

    app = QApplication(sys.argv)
    manager = ServerManager()

    # Optionally prefill the GUI's host/port fields from CLI args:
    manager.host_input.setText(args.host)
    manager.port_input.setText(str(args.port))

    manager.show()
    sys.exit(app.exec())


def main():
    """
    Main entrypoint for the 'pyservermanager' console script.
    """
    parser = argparse.ArgumentParser(
        prog="pyservermanager",
        description="CLI for PyServerManager - Run the server or launch the GUI."
    )
    subparsers = parser.add_subparsers(dest="command")

    # ---- Server Subcommand ----
    server_parser = subparsers.add_parser("server", help="Run the PyServerManager server")
    server_parser.add_argument("--host", default="localhost", help="Host/IP on which to run the server")
    server_parser.add_argument("--port", type=int, default=5050, help="Port number for client connections")
    server_parser.add_argument("--management-port", type=int, default=5051, help="Management port for the server")
    server_parser.set_defaults(func=launch_server)

    # ---- GUI Subcommand ----
    gui_parser = subparsers.add_parser("gui", help="Launch the PyServerManager GUI")
    gui_parser.add_argument("--host", default="localhost", help="Host/IP of the server's management interface")
    gui_parser.add_argument("--port", type=int, default=5051, help="Management port to connect to")
    gui_parser.set_defaults(func=launch_gui)

    args = parser.parse_args()

    # If no subcommand was provided, show help
    if not args.command:
        parser.print_help()
        sys.exit(1)

    # Call whichever function was set by the chosen subcommand
    args.func(args)


if __name__ == "__main__":
    main()
