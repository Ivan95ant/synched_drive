import logging
import socket

BROADCAST_INTERVAL = 10  # Seconds between broadcast messages


def get_local_ip():
    try:
        local_ip = socket.gethostbyname(socket.gethostname())
    except socket.error as e:
        logging.error(f"Error getting local IP address: {e}")
        local_ip = '127.0.0.1'  # Fallback to localhost
    return local_ip


def configure_logging():
    logging.basicConfig(
        level=logging.INFO,
        format='[%(asctime)s] %(levelname)s - %(filename)s:%(lineno)d - %(message)s',
        datefmt='%H:%M:%S'
    )


def broadcast_presence(broadcast_port, tcp_port, stop_event):
    """Broadcast this node's presence to the network."""
    local_ip = get_local_ip()
    message = f'NODE:{local_ip}:{tcp_port}'.encode('utf-8')
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        while not stop_event.is_set():
            sock.sendto(message, ('<broadcast>', broadcast_port))
            # logging.info("Broadcasted presence")
            stop_event.wait(BROADCAST_INTERVAL)  # Broadcast interval
    except Exception as e:
        logging.error(f'Error in broadcast_presence: {e}')
    finally:
        sock.close()


def listen_for_broadcasts(broadcast_port, tcp_port, node_manager):
    """Listen for broadcast messages and respond to new nodes."""
    local_ip = get_local_ip()
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)  # todo: remove
        sock.bind(('', broadcast_port))
        while not node_manager.stop_event.is_set():
            data, addr = sock.recvfrom(1024)
            # if addr[0] == local_ip:  # Ignore local broadcasts
            #     continue
            message = data.decode('utf-8')
            if message.startswith('NODE:'):
                _, ip, tcp_port_str = message.strip().split(':')
                remote_tcp_port = int(tcp_port_str)
                if (ip != local_ip) or (remote_tcp_port != tcp_port):
                    node_manager.connect_to_node(ip, remote_tcp_port)
    except Exception as e:
        logging.error(f'Error in listen_for_broadcasts: {e}')
    finally:
        sock.close()
