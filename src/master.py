import socket
import threading
import logging

import config
import uuid as uuid
import random
import os.path

import sys
import json
import pickle

from collections import OrderedDict
import time

import threading

class SynchronizedDict:
    def __init__(self):
        self._lock = threading.Lock()
        self._dictionary = {}

    def __getitem__(self, key):
        return self._dictionary[key]

    def __setitem__(self, key, value):
        with self._lock:
            self._dictionary[key] = value

    def __delitem__(self, key):
        with self._lock:
            del self._dictionary[key]

    def __len__(self):
        return len(self._dictionary)

    def keys(self):
        return list(self._dictionary.keys())

    def values(self):
        return list(self._dictionary.values())

    def items(self):
        return list(self._dictionary.items())



class Logger():
    def __init__(self, log_file):
        logging.basicConfig(filename=log_file, format='%(message)s')
        self.log = logging.getLogger('Master')
        self.log.setLevel(logging.INFO)
        self.root = Directory('/')
        self.restore(log_file)


    def restore(self, log_file):
        if os.path.exists(log_file):
            with open(log_file, 'r') as f:
                while True:
                    line = f.readline().strip()
                    if len(line) == 0:
                        break
                    line = line.split()
                    command = line[0]
                    if command == 'create':
                        directory, file_name = line[1], line[2]
                        directory = [part for part in directory.split('/') if part]
                        curr_dir = self.root
                        for d in directory: 
                            curr_dir = curr_dir.subdirectories[d]
                        curr_dir.add_file(file_name)
                        file = curr_dir.files[file_name]
                        file.status = FileStatus.CREATING

                    elif command == 'create_dir':
                        dir_loc, new_dir = line[1], line[2]
                        dir_loc = [part for part in dir_loc.split('/') if part]
                        curr_dir = self.root
                        for d in dir_loc:
                            curr_dir = curr_dir.subdirectories[d]
                        curr_dir.subdirectories[new_dir] = Directory(curr_dir.dfs_path + '/' + new_dir)

                    elif command == 'set_chunk_loc':
                        dfs_dir, dfs_name = line[1], line[2]
                        directory = [part for part in dfs_dir.split('/') if part]
                        curr_dir = self.root
                        for d in directory: 
                            curr_dir = curr_dir.subdirectories[d]
                        chunk_id, chunk_locs = line[3], line[4]
                        file = curr_dir.files[dfs_name]
                        file.chunks[chunk_id] = chunk_locs

                    elif command == 'delete':
                        directory, file_name = line[1], line[2]
                        directory = [part for part in directory.split('/') if part]
                        curr_dir = self.root
                        for d in directory: 
                            curr_dir = curr_dir.subdirectories[d]
                        file = curr_dir.files[file_name]
                        file.status = FileStatus.DELETED

                    elif command == 'commit_file':
                        directory, file_name = line[1], line[2]
                        directory = [part for part in directory.split('/') if part]
                        curr_dir = self.root
                        for d in directory:
                            curr_dir = curr_dir.subdirectories[d]
                        file = curr_dir.files[file_name]
                        file.status = FileStatus.COMMITTED

                    elif command == 'commit_delete':
                        directory, file_name = line[1], line[2]
                        directory = [part for part in directory.split('/') if part]
                        curr_dir = self.root
                        for d in directory:
                            curr_dir = curr_dir.subdirectories[d]
                        curr_dir.files.pop(file_name)

                    elif command == 'abort_file':
                        directory, file_name, uid = line[1], line[2], line[3]
                        directory = [part for part in directory.split('/') if part]
                        directory = directory[:-1]
                        curr_dir = self.root
                        for d in directory:
                            curr_dir = curr_dir.subdirectories[d]
                        file = curr_dir.files[file_name]
                        curr_dir.files.pop(file_name)
                        file.name = '__aborted__' + uid
                        file.status = FileStatus.ABORTED
                        curr_dir.replace_file(file)


    def log_info(self, command, args):
        if command == 'create':
            self.log.info(f'create {args[0]} {args[1]}')
        elif command == 'create_dir':
            self.log.info(f'create_dir {args[0]} {args[1]}')
        elif command == 'set_chunk_loc':
            self.log.info(f'set_chunk_loc {args[0]} {args[1]} {args[2]} {args[3]}')
        elif command == 'delete':
            self.log.info(f'delete {args[0]} {args[1]}')
        elif command == 'commit_file':
            self.log.info(f'commit_file {args[0]} {args[1]}')
        elif command == 'commit_delete':
            self.log.info(f'commit_delete {args[0]} {args[1]}')
        elif command == 'abort_file':
            self.log.info(f'abort_file {args[0]} {args[1]} {args[2]}')


class FileStatus():
    CREATING = 0
    COMMITTED = 1
    ABORTED = 2
    DELETED = 3


class Directory():
    def __init__(self, dfs_path: str):
        self.dfs_path = dfs_path
        self.files = {}
        self.subdirectories = {}

    def add_file(self, name: str):
        path = self.dfs_path + name
        self.files[name] = File(name, path)

    def replace_file(self, file):
        self.files[file.name] = file

class File():
    def __init__(self, name, dfs_path: str):
        self.name = name
        self.dfs_path = dfs_path
        self.size = 0
        self.chunks = {}
        self.status = None
        self.is_locked = False
    def __repr__(self):
        return f"Path: {self.dfs_path}, Size: {self.size}, Status: {self.status}" 
    
chunk_server_lock = threading.Lock()

class MasterServer():
    def __init__(self, host, port):
        self.host = host
        self.port = port
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind((self.host, self.port))
        self.NUM_CHUNKS = config.NUM_CHUNKS
        self.logger = Logger(config.MASTER_LOG)
        self.root = self.logger.root
        self.lock_map = {} # maps key: ip+port as string to file object
        self.system_locked = False
        self.dead_servers = []
        heart_beat_thread = threading.Thread(target=self.heart_beat_handler)
        heart_beat_thread.start()	
        chunk_audit_thread = threading.Thread(target=self.chunk_audit)
        chunk_audit_thread.start()

        # prune_chunk_thread = threading.Thread(target=self.prune_chunk_handler)
        # prune_chunk_thread.start()

        self.client_to_file_lock = SynchronizedDict()

        
    def is_alive(self, client):
        client.send(self.__respond_status(0, 'Alive'))

    def listen(self):
        self.sock.listen()
        while True:
            client, address = self.sock.accept()
            handler = threading.Thread(target=self.service, args=(client, address))
            handler.start()

    def service(self, client, address):
        ip, port = address
        connected = True
        while connected:
            try:
                message = client.recv(config.MESSAGE_SIZE)
                if message == b'':
                    raise socket.error
                if message:
                    message = json.loads(message.decode('utf-8'))
                    sender_type = message['sender_type']
                    command = message['function']
                    args = message['args']

                if sender_type == 'client':
                    if command == 'create_file':
                        self.create_file(client, args)
                    elif command == 'set_chunk_loc':
                        self.set_chunk_loc(client, args)
                    elif command == 'commit_file':
                        self.commit_file(client, args)
                    elif command == 'create_dir':
                        self.create_dir(client, args)
                    elif command == 'read_file':
                        self.read_file(client, args)
                    elif command == 'list_files':
                        self.list_files(client, args)
                    elif command == 'delete_file':
                        self.delete_file(client, args)
                    elif command == 'commit_delete':
                        self.commit_delete(client, args)
                    elif command == "file_failed":
                        self.file_failed(client, args)
                    elif command == 'close':
                        self.close_connection(client)
                        connected = False
                        print(f"Client with IP {ip} and Port {port} disconnected.")
                        
            except socket.error:
                print(f"Client with IP {ip} and Port {port} unexpectedly disconnected.")
                self.handle_client_disconnect(ip, port)
                client.close()
                connected = False 



    def handle_client_disconnect(self, ip, port):
        lock_key = str(ip) + str(port)
        if lock_key in self.client_to_file_lock.keys():
            file = self.client_to_file_lock.__getitem__(lock_key)
            directory = file.dfs_path
            directory = [part for part in directory.split('/') if part]
            directory = directory[:-1]
            curr_dir = self.root

            for d in directory:
                if d not in curr_dir.subdirectories:
                    return
                curr_dir = curr_dir.subdirectories[d]

            curr_dir.files.pop(file.name)
            dir_name = file.dfs_path
            file_name = file.name
            if file.status is not  FileStatus.COMMITTED:
                uid = str(uuid.uuid4())
                file.name = '__aborted__' + uid
                file.status = FileStatus.ABORTED
                self.logger.log_info('abort_file', [dir_name, file_name, uid])
			
    
            self.client_to_file_lock.__delitem__(lock_key)
            curr_dir.replace_file(file)

    def file_failed(self, client, args):
        directory = args[0]
        file_name = args[1]

        directory = [part for part in directory.split('/') if part]
        curr_dir = self.root
        
        for d in directory: 
            if d not in curr_dir.subdirectories:
                return
            curr_dir = curr_dir.subdirectories[d]

        if file_name in curr_dir.files:
            file = curr_dir.files[file_name]
            file.status = FileStatus.ABORTED
            # will eventually be cleaned up
        else:
            # if current client holds the lock delete it
            ip, port = client.getpeername()
            lock_key = str(ip) + str(port)
            if lock_key in self.client_to_file_lock.keys():
                self.client_to_file_lock.__delitem__(lock_key)
            
    def chunk_audit(self):
        while True:
            time.sleep(config.PRUNING_INTERVAL)
            with chunk_server_lock:
                curr_dir = self.root
                self.prune(curr_dir)
        
    def prune(self, dir : Directory):
        to_pop = []
        for file_name in list(dir.files.keys()):
            if dir.files[file_name] not in self.client_to_file_lock.values():
                if dir.files[file_name].status is not FileStatus.COMMITTED:
                    success = True
                    for chunk_id, chunk_locs in dir.files[file_name].chunks.items():
                        for idx, loc in enumerate(config.CHUNK_PORTS):
                            try:
                                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                                sock.connect((self.host, config.CHUNK_PORTS[idx]))
                                request = self.__respond_message("delete_chunk", [chunk_id])
                                sock.send(request)
                                response = sock.recv(config.MESSAGE_SIZE)
                                response = json.loads(response.decode('utf-8'))
                                if response['status'] == 0:
                                    pass
                            except Exception as e:
                                print(e)
                                success = False
                    if success:
                        to_pop.append(file_name)
                        self.logger.log_info('commit_delete', [dir.dfs_path, file_name])
        for file_name in to_pop:
            dir.files.pop(file_name)
        if len(to_pop) > 0:
            print(f"{len(to_pop)} files pruned")

        for sub_dir_name, sub_dir in dir.subdirectories.items():
            self.prune(sub_dir)
            
                
            
    def heart_beat_handler(self):
        while True:
            time.sleep(config.HEART_BEAT_INTERVAL)
            with chunk_server_lock:
                for idx, port in enumerate(config.CHUNK_PORTS):
                    try:
                        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                        sock.settimeout(config.HEART_BEAT_TIMEOUT)
                        sock.connect((self.host, port))
                        request = self.__respond_message("heartbeat", [])
                        sock.send(request)
                        response = sock.recv(config.MESSAGE_SIZE)
                        response = json.loads(response.decode('utf-8'))
                        if response['status'] == 0:
                            if idx in self.dead_servers:
                                self.dead_servers.remove(idx)
                            pass
                        else:
                            raise Exception
                    except socket.error as e:
                        print(f"Chunk Server with IP {self.host} and Port {port} not responding.")
                        self.dead_servers.append(idx)
                        sock.close()
                    except Exception as e:
                        self.dead_servers.append(idx)
                        print(f"Chunk Server with IP {self.host} and Port {port} not up.")
                        sock.close()


    def read_file(self, client, args):
        directory = args[0]
        file_name = args[1]


        directory = [part for part in directory.split('/') if part]
        curr_dir = self.root

        for d in directory: 
            if d not in curr_dir.subdirectories:
                client.send(self.__respond_status(-1, 'Directory does not exist'))
                return
            curr_dir = curr_dir.subdirectories[d]

        if file_name not in curr_dir.files:
            client.send(self.__respond_status(-1, 'File does not exist'))
        else:
            file = curr_dir.files[file_name]
            if file.status != FileStatus.COMMITTED:
                client.send(self.__respond_status(-1, 'File not committed'))
                return
            ip, port = client.getpeername()
            lock_key = str(ip) + str(port)
            self.client_to_file_lock.__setitem__(lock_key, file)
            print(f"locked file {lock_key}")
            for id, loc in file.chunks.items():
                response = {
                    'status': 0,
                    'chunk_id': id,
                    'chunk_loc': loc
                }
                response = json.dumps(response).encode('utf-8')
                response += b' ' * (config.MESSAGE_SIZE - len(response))
                client.send(response)

            client.send(self.__respond_status(1, 'Done'))
            response = client.recv(config.MESSAGE_SIZE)
            response = json.loads(response.decode('utf-8'))
            if response['status'] == 0:
                self.client_to_file_lock.__delitem__(lock_key)
                print(f"unlocked file {lock_key}")
            else:
                print(response['message'])
                self.client_to_file_lock.__delitem__(lock_key)
                print(f"unlocked file {lock_key}")



    def list_files(self, client, args):
        dfs_dir = args[0]

        directory = [part for part in dfs_dir.split('/') if part]
        curr_dir = self.root

        for d in directory: 
            if d not in curr_dir.subdirectories:
                client.send(self.__respond_status(-1, 'Directory does not exist'))
                return
            curr_dir = curr_dir.subdirectories[d]

        data = list(curr_dir.files.keys())
        data = [file for file in data if curr_dir.files[file].status == FileStatus.COMMITTED]
        directories = list(curr_dir.subdirectories.keys())
        response = {
            'status': 0,
            'data': data,
            'directories': directories
        }

        response = json.dumps(response).encode('utf-8')
        response += b' ' * (config.MESSAGE_SIZE - len(response))
        client.send(response)



    def delete_file(self, client, args):
        directory = args[0]
        file_name = args[1]

        directory = [part for part in directory.split('/') if part]
        curr_dir = self.root

        for d in directory: 
            if d not in curr_dir.subdirectories:
                client.send(self.__respond_status(-1, 'Directory does not exist'))
                return
            curr_dir = curr_dir.subdirectories[d]

        if file_name not in curr_dir.files:
            client.send(self.__respond_status(-1, 'File does not exist'))
        else:
            file = curr_dir.files[file_name]
            if file.status != FileStatus.COMMITTED:
                client.send(self.__respond_status(-1, 'File not committed'))
                print(file.status)
                return
            ip, port = client.getpeername()
            lock_key = str(ip) + str(port)


            # check if any client is currently has locked the file 
            for key in self.client_to_file_lock.keys():
                if self.client_to_file_lock.__getitem__(key) == file:
                    client.send(self.__respond_status(-1, 'File is locked by another client'))
                    return
                
            self.client_to_file_lock.__setitem__(lock_key, file)
            file.status = FileStatus.DELETED
            for id, loc in file.chunks.items():
                
                response = {
                    'status': 0,
                    'chunk_id': id,
                    'chunk_loc': loc
                }
                response = json.dumps(response).encode('utf-8')
                response += b' ' * (config.MESSAGE_SIZE - len(response))
                client.send(response)

            self.logger.log_info('delete', [args[0], args[1]])
            client.send(self.__respond_status(1, 'Done'))

    def create_file(self, client, args):
        directory = args[0]
        file_name = args[1]
        print('file name: ', file_name)

        directory = [part for part in directory.split('/') if part]
        curr_dir = self.root
        
        for d in directory: 
            if d not in curr_dir.subdirectories:
                client.send(self.__respond_status(-1, 'Directory does not exist'))
                return
            curr_dir = curr_dir.subdirectories[d]

        if file_name in curr_dir.files:
            file = curr_dir.files[file_name]
            if file.status == FileStatus.COMMITTED:	
                client.send(self.__respond_status(-1, 'File already exists'))
            else:
                client.send(self.__respond_status(-1, 'File is being written by another user'))
        else:
            curr_dir.add_file(file_name)
            file = curr_dir.files[file_name]
            file.status = FileStatus.CREATING
            ip, port = client.getpeername()
            print(f"added file {file_name} from client {ip}:{port}")
            self.logger.log_info('create', [args[0], args[1]])
            client.send(self.__respond_status(0, 'File Created'))
            lock_key = str(ip) + str(port)
            self.client_to_file_lock.__setitem__(lock_key, file)

    def set_chunk_loc(self, client, args):
        dfs_dir = args[0]
        dfs_name = args[1]
        directory = [part for part in dfs_dir.split('/') if part]
        curr_dir = self.root
        for d in directory: 
            if d not in curr_dir.subdirectories:
                client.send(self.__respond_status(-1, 'Directory does not exist'))
                return
            curr_dir = curr_dir.subdirectories[d]

        if dfs_name not in curr_dir.files:
            client.send(self.__respond_status(-1, 'File does not exist'))
        chunk_id = self._create_chunk_id()
        chunk_locs = self._sample_chunk_locs()

        file = curr_dir.files[dfs_name]

        file.chunks[chunk_id] = chunk_locs
        response = {
            'chunk_id': chunk_id,
            'chunk_locs': chunk_locs
        }

        self.logger.log_info('set_chunk_loc', [args[0], args[1], chunk_id, chunk_locs])
        response = json.dumps(response).encode('utf-8')
        response += b' ' * (config.MESSAGE_SIZE - len(response))
        client.send(response)

    def commit_file(self, client, args):
        dir = args[0]
        file_name = args[1]
        directory = [part for part in dir.split('/') if part]
        curr_dir = self.root
        for d in directory:
            if d not in curr_dir.subdirectories:
                client.send(self.__respond_status(-1, 'Directory does not exist'))
                return
            curr_dir = curr_dir.subdirectories[d]
        file = curr_dir.files[file_name]
        file.status = FileStatus.COMMITTED
        ip, port = client.getpeername()
        lock_key = str(ip) + str(port)
        self.client_to_file_lock.__delitem__(lock_key)
        self.logger.log_info('commit_file', [args[0], args[1]])
        print(f"File {file_name} committed by client {ip}:{port}")


    def create_dir(self, client, args):
        dir_loc = args[0]
        new_dir = args[1]
        print(dir_loc, new_dir)

        dir_loc = [part for part in dir_loc.split('/') if part]
        curr_dir = self.root
        
        for d in dir_loc:
            if d not in curr_dir.subdirectories:
                client.send(self.__respond_status(-1, 'Directory does not exist'))
                return
            curr_dir = curr_dir.subdirectories[d]

        if new_dir in curr_dir.subdirectories:
            client.send(self.__respond_status(-1, 'Directory already exists'))
        else:
            self.logger.log_info('create_dir', [args[0], args[1]])
            curr_dir.subdirectories[new_dir] = Directory(curr_dir.dfs_path + new_dir + '/')
            client.send(self.__respond_status(0, 'Directory Created'))
        
    def commit_delete(self, client, args):
        dir = args[0]
        file_name = args[1]
        directory = [part for part in dir.split('/') if part]
        curr_dir = self.root
        for d in directory:
            if d not in curr_dir.subdirectories:
                client.send(self.__respond_status(-1, 'Directory does not exist'))
                return
            curr_dir = curr_dir.subdirectories[d]
        file = curr_dir.files[file_name]
        ip, port = client.getpeername()
        lock_key = str(ip) + str(port)
        self.client_to_file_lock.__delitem__(lock_key)
        curr_dir.files.pop(file_name)
        self.logger.log_info('commit_delete', [args[0], args[1]])
        client.send(self.__respond_status(0, 'File Deleted'))


    def close_connection(self, client):
        client.close()

    
    def _create_chunk_id(self):
        return str(uuid.uuid4())
    
    def _sample_chunk_locs(self):
        available_ports = []
        for idx, port in enumerate(config.CHUNK_PORTS):
            if idx not in self.dead_servers:
                available_ports.append(idx)
        chunk_locs = random.sample(available_ports, min(config.REPLICATION_FACTOR, len(available_ports)))
        return chunk_locs
        

    def __respond_message(self, function, args):
        message = {
            'sender_type': 'master',
            'function': function,
            'args': args
        }
        message = json.dumps(message).encode('utf-8')
        message += b' ' * (config.MESSAGE_SIZE - len(message))
        return message

    def __respond_status(self, code, message):
        response =  {
            'status': code,
            'message': message
        }
        response = json.dumps(response).encode('utf-8')
        response += b' ' * (config.MESSAGE_SIZE - len(response))
        return response
    
    


if __name__ == '__main__':
    ms = MasterServer(config.HOST, config.MASTER_PORT)
    print("\033[H\033[J")
    print('Master Server Running')
    ms.listen()
    