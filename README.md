# Directory Synchronization Tool

This project implements a peer-to-peer directory synchronization tool written in Python. It monitors a specified directory and synchronizes changes (creations, modifications, deletions, and renames) across multiple machines on a local network.

## Table of Contents

- [Overview](#overview)
- [Modules](#modules)
- [Protocol](#protocol)
- [General Flow](#general-flow)
- [Usage](#usage)
- [Configuration](#configuration)
- [Design Considerations](#design-considerations)

## Overview

The tool uses UDP broadcasts for node discovery and TCP connections for file synchronization. It employs `pyrsync2`, a Python wrapper for `librsync`, for efficient delta encoding, ensuring that only changes within files are transmitted rather than entire files. Nodes establish persistent connections and use modification timestamps to determine the most recent changes, implementing a "last modified wins" conflict resolution strategy.

## Modules

The project is organized into the following modules:

- **`main.py`**: The entry point of the application. It initializes and starts the application, parsing command-line arguments, starting the necessary threads, and setting up the file system observer.
- **`dir_sync/event_handler.py`**: Defines the `ChangeHandler` class, which responds to file system events and initiates synchronization actions.
- **`dir_sync/file_sync.py`**: Contains functions related to file synchronization, such as generating and applying deltas using `pyrsync2`.
- **`dir_sync/node.py`**: Defines the `Node` class, representing each connected node. It manages the socket connection, synchronization state, and handles sending and receiving messages.
- **`dir_sync/node_manager.py`**: Implements the `NodeManager` class, which manages all known nodes, handles incoming connections, and coordinates synchronization.
- **`dir_sync/utils.py`**: Provides utility functions, including logging configuration and local IP address retrieval.
- **`dir_sync/__init__.py`**: An empty file that designates `dir_sync` as a Python package.

## Protocol

The synchronization protocol involves the following key components:

1. **Node Discovery**:
   - **Broadcast Presence**: Each node periodically broadcasts its presence using UDP to a designated broadcast port.
   - **Listening for Broadcasts**: Nodes listen on the broadcast port to discover other active nodes on the network.
   - **Immediate Response**: When a node discovers a new node, it immediately broadcasts its presence to inform the new node.

2. **Persistent TCP Connections**:
   - Nodes establish persistent TCP connections with each other for communication.
   - Each node maintains one connection per peer, used for all synchronization messages.

3. **Message Framing**:
   - Messages are framed with an 8-byte length prefix indicating the size of the message.
   - The message body follows the length prefix and contains the actual data, typically in JSON format and compressed using zlib.

4. **Synchronization Logic**:
   - **Initial Synchronization**:
     - Nodes exchange their directory states, including file paths, modification timestamps, and signatures.
     - Each node compares the received directory state with its own and determines which files need to be updated.
     - Files are synchronized based on the latest modification timestamps, following the "last modified wins" policy.
     - Nodes proactively send necessary files or deltas without explicit requests from peers.
   - **Modification Updates**:
     - After synchronization, nodes monitor local file changes.
     - When a change occurs, nodes generate deltas using `pyrsync2` and send `MODIFICATION_UPDATE` messages to synchronized peers.
     - Modification updates include the file path, action (create, modify, delete, rename), modification timestamp, and delta data.

5. **Conflict Resolution**:
   - Conflicts are resolved using the "last modified wins" strategy based on modification timestamps.

## General Flow

1. **Startup**:
   - The application initializes the monitored directory and necessary configurations.
   - Command-line arguments are parsed, and configuration values are passed to components.
   - Threads are started for broadcasting presence, listening for broadcasts, starting the TCP server, and running the file system observer.

2. **Node Discovery**:
   - Nodes broadcast their presence at regular intervals.
   - When a node receives a broadcast from a new node, it immediately broadcasts its own presence.
   - Nodes establish persistent TCP connections with discovered nodes.

3. **Initial Synchronization**:
   - Nodes exchange directory states and compare them.
   - Each node determines the files that the other node needs and proactively sends deltas or full files.
   - After synchronization, nodes mark each other as synchronized.

4. **File System Events**:
   - The `ChangeHandler` monitors local file changes (create, modify, delete, rename).
   - When a change is detected, a delta is generated using `pyrsync2`, and a `MODIFICATION_UPDATE` message is sent to synchronized nodes.
   - Incoming modification updates are applied if the incoming file has a newer modification timestamp.

5. **Persistent Communication**:
   - Nodes continuously listen for incoming messages on their persistent connections.
   - All synchronization messages are handled asynchronously by dedicated listener threads.

6. **Node Management**:
   - Nodes are removed from the known nodes list when their persistent connections are closed.
   - There is no need for timeout-based node removal.

## Usage

### 1. Prerequisites

- Python 3.x
- Required Python packages listed in `requirements.txt`
- `librsync` library installed on your system
- `pyrsync2` package installed from GitHub
- Ensure all nodes are on the same local network

### 2. Installation

- **Install System Dependencies**:
  - Install `librsync` (required by `pyrsync2`):
    ```bash
    sudo apt-get install librsync-dev
    ```

- **Install Required Python Packages**:
  - Install the required Python packages from `requirements.txt`:
    ```bash
    pip install -r requirements.txt
    ```

### 3. Running the Application

- Run the `main.py` script:
  ```bash
  python main.py [monitored_directory] [--broadcast-port PORT] [--listen-port PORT] [--signature-dir DIR]
  ```
    - monitored_directory: The directory to synchronize (required).
    - -b, --broadcast-port: (Optional) The UDP port for broadcasting presence (default: 5000).
    - -l, --listen-port: (Optional) The TCP port for synchronization communication (default: 6000).
    - -s, --signature-dir: (Optional) Directory to store file signatures (default: /tmp/signatures).

### 4. Examples

- Run with default settings:
  ```bash
  python main.py /path/to/directory
  ```
- Specify custom ports and signature directory:
  ```bash
  python main.py /path/to/directory -b 6000 -l 7000 -s /path/to/signatures
  ```
### 5. Monitoring Logs

  The application outputs logs to the console, providing information about synchronization events and any errors encountered.
  Logs include details about file modifications, deletions, renames, and synchronization status.

## Configuration

  - Broadcast Port: The UDP port used for node discovery. Ensure all nodes use the same broadcast port.
  - TCP Listen Port: The TCP port used for synchronization communication. Ensure all nodes use the same TCP port.
  - Monitored Directory: The directory to synchronize. Must exist before running the application.
  - Signature Directory: The directory used to store file signatures for delta computation. You can specify a custom signature directory using the --signature-dir option.

## Design Considerations

  - Node Representation:
    - Each node is represented by a Node class instance, storing the socket connection and synchronization state.
    - The NodeManager class manages all known nodes and handles incoming connections.

  - Persistent Connections:
    - Nodes establish persistent TCP connections with peers, reducing overhead and improving communication efficiency.

  - Message Framing:
    - Messages are prefixed with an 8-byte length header, allowing precise reading of messages and simplifying parsing.

  - Synchronization Strategy:
    - Nodes exchange directory states and proactively send necessary files or deltas based on modification timestamps.
    - Synchronization is performed without explicit file requests, as each node determines what data the other node needs.

  - Conflict Resolution:
    - Implements a "last modified wins" policy, where the most recently modified file is propagated.

  - Event Handling:
    - The application maintains an ignore list to prevent processing file system events triggered by remote updates.
    - The ChangeHandler ignores events for files in the ignore list.

  - Modular Design:
    - The code is organized into modules with clear responsibilities, improving maintainability.

---
This tool facilitates real-time synchronization of directories across multiple machines on a local network, ensuring that changes made on one node are propagated to all others efficiently and reliably.
