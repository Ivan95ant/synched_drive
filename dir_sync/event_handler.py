import logging
import os
import time

from watchdog.events import FileSystemEventHandler

from dir_sync.file_sync import FileSync


class ChangeHandler(FileSystemEventHandler):
    def __init__(self, monitored_directory, node_manager):
        super().__init__()
        self.monitored_directory = monitored_directory
        self.node_manager = node_manager
        self.last_trigger_time = time.time_ns()

    def should_ignore(self, event):
        event_time = time.time_ns()
        if event.is_directory:
            return True

        full_path = os.path.abspath(event.src_path)
        ignore_time = self.node_manager.ignore_events.get(full_path)

        if ignore_time:
            # Define 500 milliseconds in nanoseconds - half a second
            if event_time < ignore_time + 500_000_000:
                logging.info(f"ignoring event created by ourself")
                return True
            else:
                self.node_manager.ignore_events.pop(full_path)

        return False

    def on_modified(self, event):
        if self.should_ignore(event):
            return

        current_time = time.time_ns()
        if event.src_path.find('~') == -1 and (current_time - self.last_trigger_time) > 100_000_000:
            self.last_trigger_time = current_time
            self.handle_modify_create(event.src_path, action='MODIFY')

    def on_created(self, event):
        # todo: might be pointless if creation triggers modification
        if self.should_ignore(event):
            return
        self.handle_modify_create(event.src_path, action='CREATE')

    def on_deleted(self, event):
        if self.should_ignore(event):
            return

        relative_path = os.path.relpath(event.src_path, self.monitored_directory)
        # Remove the stored signature
        signature_file_path = FileSync.get_signature_file_path(relative_path)
        if os.path.exists(signature_file_path):
            os.remove(signature_file_path)
        payload = {
            'file_path': relative_path,
            'action': 'DELETE',
            'mtime': time.time()
        }
        self.node_manager.broadcast_update(payload)
        logging.info(f"File deleted: {relative_path}")

    def on_moved(self, event):
        if self.should_ignore(event):
            return
        src_relative_path = os.path.relpath(event.src_path, self.monitored_directory)
        dest_relative_path = os.path.relpath(event.dest_path, self.monitored_directory)
        # Move the signature file
        src_signature_path = FileSync.get_signature_file_path(src_relative_path)
        dest_signature_path = FileSync.get_signature_file_path(dest_relative_path)
        if os.path.exists(src_signature_path):
            os.makedirs(os.path.dirname(dest_signature_path), exist_ok=True)
            os.rename(src_signature_path, dest_signature_path)
        payload = {
            'file_path': src_relative_path,
            'dest_path': dest_relative_path,
            'action': 'RENAME',
            'mtime': time.time()
        }
        self.node_manager.broadcast_update(payload)
        logging.info(f"File renamed from {src_relative_path} to {dest_relative_path}")

    def handle_modify_create(self, src_path, action):
        relative_path = os.path.relpath(src_path, self.monitored_directory)
        try:
            stat = os.stat(src_path)
            # Load the old signature (if any)
            old_signature = FileSync.load_signature(relative_path)
            # Compute the new signature
            new_signature = FileSync.compute_signature(src_path)
            # Generate delta
            if old_signature:
                # Generate delta using the old signature
                delta_data = FileSync.generate_delta(old_signature, src_path)
                is_full_file = False
            else:
                # If no old signature, send the full file
                with open(src_path, 'rb') as f:
                    delta_data = [f.read()]
                is_full_file = True
            # Save the new signature
            FileSync.save_signature(new_signature, relative_path)
            serialized_delta = FileSync.serialize_delta_data(delta_data)
            payload = {
                'file_path': relative_path,
                'delta': serialized_delta,
                'mtime': stat.st_mtime,
                'action': action,
                'is_full_file': is_full_file
            }
            self.node_manager.broadcast_update(payload)
            logging.info(f"File {action.lower()}d: {relative_path}")
        except Exception as e:
            logging.error(f"Error handling file {relative_path}: {e}")
