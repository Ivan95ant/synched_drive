import base64
import os
import shutil
import struct
import tempfile
import zlib

import pyrsync2  # noqa: module 'pyrsync2' is provided by 'git+https://github.com/dani-sev/pyrsync'

DEFAULT_SIGNATURES_DIR = '/tmp/signatures'
SIGNATURE_PACK = "L16s"


class FileSync:
    signatures_dir = DEFAULT_SIGNATURES_DIR

    @classmethod
    def initialize_signatures_dir(cls):
        """Initialize the signatures directory by removing any existing signatures."""
        if os.path.exists(cls.signatures_dir):
            shutil.rmtree(cls.signatures_dir)
        os.makedirs(cls.signatures_dir, exist_ok=True)

    @classmethod
    def compute_signature(cls, file_path):
        """Compute block checksums for a file."""
        with open(file_path, 'rb') as f:
            signature = list(pyrsync2.blockchecksums(f))
        return signature

    @classmethod
    def save_signature(cls, signature, relative_file_path):
        """Save the computed checksums to a compressed binary file in the signatures directory."""
        signature_file_path = cls.get_signature_file_path(relative_file_path)
        # Ensure the directory exists
        os.makedirs(os.path.dirname(signature_file_path), exist_ok=True)
        # Flatten the signature data into a byte array
        flattened_data = b""
        for weak_checksum, strong_checksum in signature:
            # Pack weak checksum (long) and strong checksum (16-byte MD5 hash) into binary format
            flattened_data += struct.pack(SIGNATURE_PACK, weak_checksum, strong_checksum)

        # Compress the data and save it
        compressed_data = zlib.compress(flattened_data)
        with open(signature_file_path, 'wb') as sig_file:
            sig_file.write(compressed_data)

        return compressed_data

    @classmethod
    def parse_signature(cls, signature_data):
        # Decompress the data
        flattened_data = zlib.decompress(signature_data)

        # Unpack the binary data into signature tuples
        signature = []
        for i in range(0, len(flattened_data), struct.calcsize(SIGNATURE_PACK)):
            sig = struct.unpack(SIGNATURE_PACK,
                                flattened_data[i:i + struct.calcsize(SIGNATURE_PACK)])
            signature.append(sig)
        return signature

    @classmethod
    def load_signature(cls, relative_file_path):
        """Load stored checksums from a compressed binary file."""
        signature_file_path = cls.get_signature_file_path(relative_file_path)
        if not os.path.exists(signature_file_path):
            return None
        with open(signature_file_path, 'rb') as sig_file:
            compressed_data = sig_file.read()

        return cls.parse_signature(compressed_data)

    @classmethod
    def get_signature_file_path(cls, relative_file_path):
        """Get the path to the signature file corresponding to the given file."""
        signature_file_path = os.path.join(cls.signatures_dir, relative_file_path + '.sig')
        return signature_file_path

    @classmethod
    def generate_delta(cls, signature_data, new_file_path):
        """Generate a delta between the stored checksums and the new file."""
        with open(new_file_path, 'rb') as new_file:
            return list(pyrsync2.rsyncdelta(new_file, signature_data))

    @classmethod
    def apply_delta(cls, base_file_path, delta_data):
        """Apply a delta to the base file to reconstruct the modified file in place."""
        # Create a temporary file
        with tempfile.NamedTemporaryFile(delete=False) as temp_file:
            temp_file_path = temp_file.name

        try:
            # Apply the delta to reconstruct the modified file in the temporary file
            with open(base_file_path, 'rb') as base_file, open(temp_file_path, 'wb') as temp_output_file:
                pyrsync2.patchstream(base_file, temp_output_file, delta_data)

            # Replace the original file with the reconstructed file
            os.replace(temp_file_path, base_file_path)
        finally:
            # Ensure the temporary file is deleted
            if os.path.exists(temp_file_path):
                os.remove(temp_file_path)

    @classmethod
    def serialize_delta_data(cls, delta_data):
        """Serialize delta data into a JSON-serializable format."""
        serialized = []
        for item in delta_data:
            if isinstance(item, int):
                serialized.append(item)
            elif isinstance(item, bytes):
                serialized.append(base64.b64encode(item).decode('ascii'))
            else:
                raise ValueError(f"Unsupported type in delta_data: {type(item)}")
        return serialized

    @classmethod
    def deserialize_delta_data(cls, serialized_data):
        """Deserialize delta data from the JSON-serializable format."""
        delta_data = []
        for item in serialized_data:
            if isinstance(item, int):
                delta_data.append(item)
            elif isinstance(item, str):
                delta_data.append(base64.b64decode(item))
            else:
                raise ValueError(f"Unsupported type in delta_data: {type(item)}")
        return delta_data
