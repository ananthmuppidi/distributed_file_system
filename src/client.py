import socket
import pickle
import os.path
import threading
import time

import config
import json



class Client():
	def __init__(self):
		self.master = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
		# self.master.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
		self.master.connect((socket.gethostbyname('localhost'), config.MASTER_PORT))

	def create_dir(self, dfs_dir, new_dir):
		request = self._get_message_data('create_dir', dfs_dir, new_dir)
		self.master.sendall(request)
		response = self.master.recv(config.MESSAGE_SIZE)
		response = json.loads(response.decode('utf-8'))
		print(response['message'])

	def create_file(self, local_path, dfs_dir, dfs_name):
		print(local_path, dfs_dir, dfs_name)
		request = self._get_message_data('create_file', dfs_dir, dfs_name)
		self.master.sendall(request)
		response = self.master.recv(config.MESSAGE_SIZE)
		response = json.loads(response.decode('utf-8'))
		if response['status'] == -1:
			print(response['message'])
			return

		num_bytes = os.path.getsize(local_path)
		chunks = num_bytes // config.CHUNK_SIZE + int(num_bytes%config.CHUNK_SIZE != 0)
		for chunk in range(chunks):
			request = self._get_message_data('set_chunk_loc', dfs_dir, dfs_name)
			self.master.send(request)
			response = self.master.recv(config.MESSAGE_SIZE)
			response = json.loads(response.decode('utf-8'))
			chunk_id = response['chunk_id']
			chunk_locs = response['chunk_locs']

			with open(local_path, 'rb') as f:
				f.seek(chunk * config.CHUNK_SIZE)
				data = f.read(config.CHUNK_SIZE)

			for chunk_loc in chunk_locs:
				chunk_server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
				chunk_server.connect((socket.gethostbyname('localhost'), config.CHUNK_PORTS[chunk_loc]))
				request = self._get_message_data('write_chunk', chunk_id)	
				chunk_server.sendall(request)
				chunk_server.sendall(data)

			chunk_server.close()
		self.master.send(self._get_message_data("commit_file", dfs_dir, dfs_name))


	def read_file(self, dfs_dir, dfs_name):
		request = self._get_message_data('read_file', dfs_dir, dfs_name)
		self.master.sendall(request)
		chunk_ids, chunks_locs = [], []
		while True:
			response = self.master.recv(config.MESSAGE_SIZE)
			response = json.loads(response.decode('utf-8'))
			if response['status'] == 1:
				break
			chunk_ids.append(response['chunk_id'])
			chunks_locs.append(response['chunk_loc'])

		data = ''
		final_success = True
		for id, locs in zip(chunk_ids, chunks_locs):
			success = False
			for loc in locs:
				if success == False:
					try:
						time.sleep(0.2)
						chunk_server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
						chunk_server.connect((socket.gethostbyname('localhost'), config.CHUNK_PORTS[int(loc)]))
						request = self._get_message_data('read_chunk', id)	
						chunk_server.sendall(request)
						response = chunk_server.recv(config.MESSAGE_SIZE)
						response = json.loads(response.decode('utf-8'))
						if response['status'] == -1:
							print("line 85")
							success = False
						else:
							data += response['data']
							success = True
					except Exception as e:
						print(loc)
						print(e)
						print("line 91")
						success = False
				else:
					break
			if success == False:
				final_success = False
				break
		
		if final_success == False:
			print("Can't read file now. Try again later")
			self.master.send(self._get_status_data(-1, "Can't read file now. Try again later"))
		else:
			self.master.send(self._get_status_data(0, "ok"))
			print(data)
		
	
	def list_files(self, dfs_dir):

		request = self._get_message_data('list_files', dfs_dir)
		self.master.sendall(request)
		response = self.master.recv(config.MESSAGE_SIZE)
		response = json.loads(response.decode('utf-8'))
		if response['status'] == -1:
			print(response['message'])
			return
		for file in response['data']:
			print(file)


	def delete_file(self, dfs_dir, dfs_name):
		fail = False

		request = self._get_message_data('delete_file', dfs_dir, dfs_name)
		self.master.sendall(request)
		chunk_ids, chunks_locs = [], []
		while True:
			response = self.master.recv(config.MESSAGE_SIZE)
			response = json.loads(response.decode('utf-8'))
			# print(response)
			if response['status'] == -1:
				print(response['message'])
				fail = True
				break
			if response['status'] == 1:
				break
			chunk_ids.append(response['chunk_id'])
			chunks_locs.append(response['chunk_loc'])
		if not fail:
			for id, locs in zip(chunk_ids, chunks_locs):
				for loc in locs:
					chunk_server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
					chunk_server.connect((socket.gethostbyname('localhost'), config.CHUNK_PORTS[loc]))
					request = self._get_message_data('delete_chunk', id)	
					chunk_server.sendall(request)
					response = chunk_server.recv(config.MESSAGE_SIZE)
					response = json.loads(response.decode('utf-8'))
					if response['status'] == -1:
						print(response['message'])
						return
					chunk_server.close()
			self.master.send(self._get_message_data("commit_delete", dfs_dir, dfs_name))
			self.master.recv(config.MESSAGE_SIZE)
			if response['status'] != 0:
				print(response['message'])
			else:
				print(f"Deleted {dfs_name}")

	def close_connection(self):
			request = self._get_message_data('close', '')
			self.master.sendall(request)
			self.master.close()

	def _get_message_data(self, function, *args):
		function = function
		message = {
			'sender_type': 'client',
			'function': function,
			'args': args
		}
		encoded = json.dumps(message).encode('utf-8')
		encoded += b' ' * (config.MESSAGE_SIZE - len(encoded))
		return encoded



	def _get_status_data(self, status, message):
		message = {
			'status': status,
			'message': message
		}
		encoded = json.dumps(message).encode('utf-8')
		encoded += b' ' * (config.MESSAGE_SIZE - len(encoded))
		return encoded



		
			

		

if __name__ == '__main__':
	client = Client()
	print('\033c')
	print('\033[2J')
	while True:
		command = input('$ ')
		words = command.split()
		command, args = words[0], words[1:]


		if command == 'ls':
			# usage ls <dfs_directory>
			client.list_files(args[0])
		elif command == 'delete':
			# usage delete <dfs_directory> <dfs_name>
			client.delete_file(args[0], args[1])
		elif command == 'read':
			# usage read <dfs_directory> <dfs_name>
			client.read_file(args[0], args[1])
		elif command == 'create':
			# usage create <local_file> <dfs_directory> <dfs_name>
			client.create_file(args[0], args[1], args[2])
		elif command == 'create_dir':
			# usage create_dir <dfs_directory> <directory_name>
			client.create_dir(args[0], args[1])
		elif command == 'exit':
			client.close_connection()
			print("Exiting...")
			break
		else:
			print(f"{command}: command not found")