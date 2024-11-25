import argparse
import logging
import threading
import time

from watchdog.observers import Observer

from dir_sync.event_handler import ChangeHandler
from dir_sync.file_sync import FileSync, DEFAULT_SIGNATURES_DIR
from dir_sync.node_manager import NodeManager
from dir_sync.utils import configure_logging, broadcast_presence, listen_for_broadcasts


def parse_arguments():
    parser = argparse.ArgumentParser(description='Directory Synchronization Tool')
    parser.add_argument(
        'monitor_dir',
        nargs='?',
        help='The directory to monitor and synchronize'
    )
    parser.add_argument(
        '-s',
        '--signature_dir',
        nargs='?',
        default=DEFAULT_SIGNATURES_DIR,
        help='The directory to monitor and synchronize'
    )
    parser.add_argument(
        '-b',
        '--broadcast-port',
        type=int,
        default=5000,
        help='The UDP port for broadcasting presence (default: 5000)'
    )
    parser.add_argument(
        '-l',
        '--listen-port',
        type=int,
        default=6000,
        help='The TCP port for synchronization communication listening(default: 6000)'
    )
    return parser.parse_args()


def main():
    # Configure logging
    configure_logging()

    # Parse command-line arguments
    args = parse_arguments()

    FileSync.signatures_dir = args.signature_dir

    # Initialize the signatures directory
    FileSync.initialize_signatures_dir()

    # Initialize NodeManager
    node_manager = NodeManager(args.monitor_dir, args.listen_port)

    # Start threads for broadcasting and listening
    threading.Thread(
        target=broadcast_presence,
        args=(args.broadcast_port, args.listen_port, node_manager.stop_event),
        daemon=True
    ).start()
    threading.Thread(
        target=listen_for_broadcasts,
        args=(args.broadcast_port, args.listen_port, node_manager),
        daemon=True
    ).start()

    # Start the TCP server
    threading.Thread(
        target=node_manager.start_tcp_server,
        daemon=True
    ).start()

    # Start the file system observer
    event_handler = ChangeHandler(
        args.monitor_dir,  # Corrected here
        node_manager
    )
    observer = Observer()
    observer.schedule(event_handler, path=args.monitor_dir, recursive=True)  # Corrected here
    observer.start()
    logging.info("File system observer started")

    # Keep the main thread alive
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        node_manager.stop()
        observer.stop()
        observer.join()
        print("Directory Synchronization Tool stopped.")



if __name__ == '__main__':
    main()
