import logging
import socket
import threading

from dir_sync.node import Node


class NodeManager:
    def __init__(self, monitored_directory, tcp_port):
        self.nodes = {}
        self.lock = threading.Lock()
        self.monitored_directory = monitored_directory
        self.tcp_port = tcp_port
        self.ignore_events = dict()
        self.stop_event = threading.Event()

    def connect_to_node(self, ip, tcp_port):
        """Initiate a connection to a remote node and add it."""
        node_id = (ip, tcp_port)
        try:
            with self.lock:
                if node_id not in self.nodes:
                    logging.info(f"Connecting to new node {ip}:{tcp_port}")
                    sock = socket.create_connection((ip, tcp_port))
                    self.add_node_unsafe(ip, tcp_port, sock)
                else:
                    # logging.info(f"Node {ip}:{tcp_port} already exists")
                    pass
        except Exception as e:
            logging.error(f"Error connecting to {ip}:{tcp_port}: {e}")

    def add_node_unsafe(self, ip, tcp_port, conn):
        """Add a node with an existing connection. unsafe because assuming lock aquired."""
        node_id = (ip, tcp_port)
        node = Node(ip, tcp_port, conn, self)
        self.nodes[node_id] = node
        node.start_listener()
        node.synchronize()
        logging.info(f"Added node {ip}:{tcp_port}")

    def remove_node(self, ip, tcp_port):
        node_id = (ip, tcp_port)
        with self.lock:
            if node_id in self.nodes:
                node = self.nodes[node_id]
                node.close_connection()
                del self.nodes[node_id]
                logging.info(f"Removed node {ip}:{tcp_port}")

    def start_tcp_server(self):
        """Start a TCP server to accept incoming connections."""
        server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server_sock.bind(('', self.tcp_port))
        server_sock.listen()
        logging.info(f"TCP server listening on port {self.tcp_port}")
        try:
            while not self.stop_event.is_set():
                conn, addr = server_sock.accept()
                ip = addr[0]
                threading.Thread(
                    target=self.handle_incoming_connection,
                    args=(conn, ip),
                    daemon=True
                ).start()
        except Exception as e:
            logging.error(f"Error in TCP server: {e}")
        finally:
            server_sock.close()

    def handle_incoming_connection(self, conn, ip):
        """Handle an incoming TCP connection."""
        try:
            remote_tcp_port = conn.getpeername()[1]
            node_id = (ip, remote_tcp_port)

            with self.lock:
                if node_id not in self.nodes:
                    logging.info(f"Incoming connecting from a new node {ip}:{remote_tcp_port}")
                    self.add_node_unsafe(ip, remote_tcp_port, conn)
                else:
                    logging.info(f"Node {ip}:{remote_tcp_port} already exists")

        except Exception as e:
            logging.error(f"Error handling incoming connection from {ip}: {e}")

    def broadcast_update(self, payload):
        logging.info(f"sending action: {payload.get('action')}, delta: {payload.get('delta', 'NONE')}")
        with self.lock:
            for node in self.nodes.values():
                if node.is_synchronized:
                    logging.info(f"Sending update to node {node.ip}:{node.tcp_port}")
                    node.send_message('MODIFICATION_UPDATE', payload)

    def stop(self):
        self.stop_event.set()
        with self.lock:
            for node in list(self.nodes.values()):
                node.close_connection()
            self.nodes.clear()
