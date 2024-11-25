import base64
import json
import logging
import os
import struct
import threading
import time
import traceback
import zlib

from dir_sync.file_sync import FileSync


class Node:
    def __init__(self, ip, tcp_port, sock, node_manager):
        self.ip = ip
        self.tcp_port = tcp_port
        self.socket = sock
        self.node_manager = node_manager  # Reference to NodeManager
        self.monitored_directory = node_manager.monitored_directory
        self.is_synchronized = False
        self.lock = threading.Lock()
        self.buffer = b''
        self.stop_event = threading.Event()

    def send_message(self, message_type, payload):
        with self.lock:
            try:
                message = {
                    'type': message_type,
                    'payload': payload
                }
                message_bytes = json.dumps(message).encode('utf-8')
                compressed_message = zlib.compress(message_bytes)
                length_prefix = struct.pack('>Q', len(compressed_message))
                self.socket.sendall(length_prefix + compressed_message)
                logging.info(f"Sent {message_type} message to {self.ip}:{self.tcp_port}")
            except Exception as e:
                logging.error(f"Error sending message to {self.ip}:{self.tcp_port}: {e}")
                self.close_connection()

    def start_listener(self):
        threading.Thread(target=self.listen_for_messages, daemon=True).start()

    def listen_for_messages(self):
        try:
            while not self.stop_event.is_set():
                message = self.receive_message()
                if message:
                    self.handle_message(message)
                else:
                    break
        except Exception as e:
            logging.error(f"Error in listener for node {self.ip}:{self.tcp_port}: {e}")
            tb = traceback.extract_tb(e.__traceback__)
            if tb:  # Ensure traceback is not empty
                source = f"{tb[-1].filename}:{tb[-1].lineno}"
            else:
                source = "Unknown source"

            # Log the error with source information
            logging.error(f"Error connecting to at {source}: {e}")
        finally:
            self.close_connection()
            self.node_manager.remove_node(self.ip, self.tcp_port)

    def receive_message(self):
        try:
            # Read length prefix
            while len(self.buffer) < 8:
                data = self.socket.recv(4096)
                if not data:
                    raise ConnectionError("Connection closed by peer")
                self.buffer += data
            length_prefix = self.buffer[:8]
            self.buffer = self.buffer[8:]
            message_length = struct.unpack('>Q', length_prefix)[0]

            # Read message body
            while len(self.buffer) < message_length:
                data = self.socket.recv(4096)
                if not data:
                    raise ConnectionError("Connection closed by peer")
                self.buffer += data
            message_body = self.buffer[:message_length]
            self.buffer = self.buffer[message_length:]

            # Decompress and parse message
            decompressed_message = zlib.decompress(message_body)
            message = json.loads(decompressed_message.decode('utf-8'))
            return message
        except Exception as e:
            logging.error(f"Error receiving message from {self.ip}:{self.tcp_port}: {e}")
            self.close_connection()
            return None

    def synchronize(self):
        # Send our directory state
        local_state = self.get_local_directory_state_with_signatures()
        self.send_message('DIRECTORY_STATE', local_state)
        logging.info(f"Sent DIRECTORY_STATE to {self.ip}:{self.tcp_port}")

    def get_local_directory_state_with_signatures(self):
        directory_state = {}
        for root, _, files in os.walk(self.monitored_directory):
            for file in files:
                file_path = os.path.join(root, file)
                relative_path = os.path.relpath(file_path, self.monitored_directory)
                stat = os.stat(file_path)
                # Compute signature and save it
                signature = FileSync.compute_signature(file_path)
                compressed_sig = FileSync.save_signature(signature, relative_path)
                directory_state[relative_path] = {
                    'mtime': stat.st_mtime,
                    'size': stat.st_size,
                    'signature': base64.b64encode(compressed_sig).decode('ascii'),
                }
        return directory_state

    def handle_message(self, message):
        message_type = message.get('type')
        payload = message.get('payload')

        if message_type == 'DIRECTORY_STATE':
            self.handle_directory_state(payload)
        elif message_type == 'DELTA_TRANSFER':
            self.handle_delta_transfer(payload)
        elif message_type == 'MODIFICATION_UPDATE':
            self.handle_modification_update(payload)
        else:
            logging.warning(f"Unknown message type {message_type} from {self.ip}:{self.tcp_port}")

    def handle_directory_state(self, remote_state):
        # Compare remote directory state with local and send necessary deltas/files
        local_state = self.get_local_directory_state_with_signatures()
        files_to_send = {}

        # Determine files to send
        all_files = set(local_state.keys()).union(set(remote_state.keys()))
        for file_path in all_files:
            local_file = local_state.get(file_path)
            remote_file = remote_state.get(file_path)

            if local_file and remote_file:
                # Both nodes have the file
                if local_file['mtime'] > remote_file['mtime']:
                    # Local file is newer
                    compressed_signature = base64.b64decode(remote_file['signature'])
                    signature = FileSync.parse_signature(compressed_signature)
                    files_to_send[file_path] = self.prepare_file_for_transfer(file_path, signature)
                else:
                    # Remote file is newer; no action needed
                    # mtime is equal, no action needed
                    continue
            elif local_file and not remote_file:
                # File exists locally but not remotely
                files_to_send[file_path] = self.prepare_file_for_transfer(file_path)
            # If file exists remotely but not locally, the peer will send it to us

        # Send deltas/files
        if files_to_send:
            self.send_message('DELTA_TRANSFER', files_to_send)
            logging.info(f"Sent DELTA_TRANSFER to {self.ip}:{self.tcp_port}")

        # After handling DIRECTORY_STATE and sending necessary files, mark as synchronized
        self.is_synchronized = True
        logging.info(f"Synchronized with node {self.ip}:{self.tcp_port}")

    def prepare_file_for_transfer(self, relative_path, signature=None):
        file_path = os.path.join(self.monitored_directory, relative_path)
        # Compute the new signature
        # Generate delta
        if signature:
            # Generate delta using the remote signature
            delta_data = FileSync.generate_delta(signature, file_path)
            is_full_file = False
        else:
            # If no remote signature, send the full file
            with open(file_path, 'rb') as f:
                delta_data = [f.read()]
            is_full_file = True

        # Save the new signature
        # new_signature = FileSync.compute_signature(file_path)
        # FileSync.save_signature(new_signature, relative_path)

        serialized_delta = FileSync.serialize_delta_data(delta_data)
        stat = os.stat(file_path)
        return {
            'delta': serialized_delta,
            'mtime': stat.st_mtime,
            'action': 'CREATE',
            'is_full_file': is_full_file
        }

    def handle_delta_transfer(self, payload):
        for file_path, file_info in payload.items():
            full_path = os.path.abspath(os.path.join(self.monitored_directory, file_path))
            os.makedirs(os.path.dirname(full_path), exist_ok=True)
            mtime = file_info['mtime']
            action = file_info.get('action', 'CREATE')
            is_full_file = file_info.get('is_full_file', False)

            serialized_delta = file_info.get('delta')
            delta_data = FileSync.deserialize_delta_data(serialized_delta) if serialized_delta else []

            # Add to ignore a list to prevent triggering local events
            self.node_manager.ignore_events[full_path] = time.time_ns()

            try:
                if delta_data:
                    if is_full_file:
                        # Write the full file content
                        with open(full_path, 'wb') as f:
                            f.write(b''.join(delta_data))
                    else:
                        # Apply the delta
                        old_signature = FileSync.load_signature(file_path)
                        if not old_signature:
                            logging.warning(f"No signature found for {file_path}, cannot apply delta.")
                            continue
                        FileSync.apply_delta(full_path, delta_data)
                else:
                    # Empty delta indicates an empty file
                    open(full_path, 'wb').close()
                os.utime(full_path, (mtime, mtime))
                logging.info(f"Received file {file_path}")
                # Compute and save the new signature
                new_signature = FileSync.compute_signature(full_path)
                FileSync.save_signature(new_signature, file_path)
            except Exception as e:
                logging.error(f"Error applying delta to {file_path}: {e}")

    def handle_modification_update(self, payload):
        file_path = payload.get('file_path')
        mtime = payload.get('mtime')
        action = payload.get('action')
        is_full_file = payload.get('is_full_file', False)

        full_path = os.path.abspath(os.path.join(self.monitored_directory, file_path))

        logging.info(f"update from remote, action: {action}")

        # Add to ignore a list to prevent triggering local events
        self.node_manager.ignore_events[full_path] = time.time_ns()

        if action == 'MODIFY' or action == 'CREATE':
            serialized_delta = payload.get('delta')
            delta_data = FileSync.deserialize_delta_data(serialized_delta)
            logging.info(f"GOT action: {action}, delta: {delta_data}")
            try:
                if delta_data:
                    if is_full_file:
                        # Write the full file content
                        with open(full_path, 'wb') as f:
                            f.write(b''.join(delta_data))
                    else:
                        # Apply the delta
                        if not os.path.exists(full_path):
                            logging.warning(f"Base file for delta does not exist: {file_path}")
                            return

                        FileSync.apply_delta(full_path, delta_data)
                else:
                    # Empty delta indicates an empty file
                    open(full_path, 'wb').close()
                os.utime(full_path, (mtime, mtime))
                logging.info(f"File {action.lower()}d: {file_path}")
                # Compute and save the new signature
                new_signature = FileSync.compute_signature(full_path)
                FileSync.save_signature(new_signature, file_path)
            except Exception as e:
                logging.error(f"Error applying delta to {file_path}: {e}")
        elif action == 'DELETE':
            if os.path.exists(full_path):
                os.remove(full_path)
                logging.info(f"File deleted: {file_path}")
            # Remove signature
            signature_file_path = FileSync.get_signature_file_path(file_path)
            if os.path.exists(signature_file_path):
                os.remove(signature_file_path)
        elif action == 'RENAME':
            dest_path = payload.get('dest_path')
            dest_full_path = os.path.join(self.monitored_directory, dest_path)
            os.makedirs(os.path.dirname(dest_full_path), exist_ok=True)
            if os.path.exists(full_path):
                os.rename(full_path, dest_full_path)
                logging.info(f"File renamed from {file_path} to {dest_path}")
            # Move signature file
            src_signature_path = FileSync.get_signature_file_path(file_path)
            dest_signature_path = FileSync.get_signature_file_path(dest_path)
            if os.path.exists(src_signature_path):
                os.makedirs(os.path.dirname(dest_signature_path), exist_ok=True)
                os.rename(src_signature_path, dest_signature_path)
            else:
                logging.warning(f"Signature file not found for {file_path}")

    def close_connection(self):
        self.stop_event.set()
        with self.lock:
            if self.socket:
                try:
                    self.socket.close()
                except Exception as e:
                    logging.error(f"Error closing connection to {self.ip}:{self.tcp_port}: {e}")
                self.socket = None
