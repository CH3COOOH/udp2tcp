import ipaddress
import socket
import struct
import threading

from const import *
from socket_util import read_frame, reset_tcp_connection, pack_datagram_frame, unpack_datagram_frame

from debug import debug

def log(msg):
	print("[tcp_client_handler] " + msg)

class TcpClientHandler:
	"""
	Handler for a single TCP client connection in TCP-to-UDP mode.
	
	Reads framed messages from the TCP client, creates UDP flows to the remote
	server, and handles bidirectional communication.
	"""
	
	def __init__(self, conn, client_addr, udp_family, udp_target, cipher=None):
		self.conn = conn
		self.client_addr = client_addr
		self.udp_family = udp_family
		self.udp_target = udp_target
		self.cipher = cipher
		self.stop_event = threading.Event()
		self.flow_lock = threading.Lock()
		self.flows = {}
		self.send_lock = threading.Lock()
		log(f"[t2u] TCP client connected: {client_addr}")

	def send_back_to_tcp(self, endpoint, payload):
		frame = pack_datagram_frame(MSG_REMOTE_TO_UDP, endpoint, payload, cipher=self.cipher)
		log(f"send_back_to_tcp: sending {len(payload)} bytes to TCP endpoint {endpoint}")
		with self.send_lock:
			try:
				self.conn.sendall(frame)
			except OSError as exc:
				log(f"Send back to TCP failed for {endpoint}: {exc}")
				self.stop_event.set()
				raise

	def get_or_create_flow(self, endpoint):
		with self.flow_lock:
			flow = self.flows.get(endpoint)
			if flow is not None:
				return flow

			flow_sock = socket.socket(self.udp_family, socket.SOCK_DGRAM)
			flow_sock.connect(self.udp_target)
			thread = threading.Thread(
				target=self.reply_reader,
				args=(endpoint, flow_sock),
				daemon=True,
			)
			thread.start()
			self.flows[endpoint] = (flow_sock, thread)
			return self.flows[endpoint]

	def reply_reader(self, endpoint, flow_sock):
		"""
		Read UDP replies from the remote UDP target and forward them back to the TCP client.
		"""
		flow_sock.settimeout(1.0)
		try:
			while not self.stop_event.is_set():
				try:
					payload = flow_sock.recv(BUFFER_SIZE)
				except socket.timeout:
					continue
				except OSError as exc:
					if self.stop_event.is_set():
						break
					log(f"UDP reply receive failed for {endpoint}: {exc}")
					break
				if not payload:
					break
				try:
					self.send_back_to_tcp(endpoint, payload)
				except OSError:
					break
		finally:
			with self.flow_lock:
				self.flows.pop(endpoint, None)
			try:
				flow_sock.close()
			except OSError:
				pass

	def run(self):
		with self.conn:
			try:
				while True:
					frame_body = read_frame(self.conn)
					if frame_body is None:
						break
					try:
						msg_type, endpoint, payload = unpack_datagram_frame(frame_body, cipher=self.cipher)
					except ValueError as exc:
						log(f"[t2u] Invalid TCP frame from {self.client_addr}: {exc}")
						reset_tcp_connection(self.conn)
						return
					if msg_type != MSG_UDP_TO_REMOTE:
						log(f"[t2u] Invalid TCP frame type from {self.client_addr}: {msg_type}")
						reset_tcp_connection(self.conn)
						return

					flow_sock, _ = self.get_or_create_flow(endpoint)
					try:
						flow_sock.send(payload)
					except OSError as exc:
						log(f"[t2u] UDP send failed for {endpoint} -> {self.udp_target}: {exc}")
						with self.flow_lock:
							self.flows.pop(endpoint, None)
						try:
							flow_sock.close()
						except OSError:
							pass
						continue
					log(f"[t2u] TCP {endpoint} -> UDP {self.udp_target}, {len(payload)} bytes")
			except OSError as exc:
				log(f"[t2u] Client handling failed for {self.client_addr}: {exc}")
			finally:
				self.stop_event.set()
				with self.flow_lock:
					for flow_sock, _thread in self.flows.values():
						try:
							flow_sock.close()
						except OSError:
							pass
					self.flows.clear()
				log(f"[t2u] TCP client disconnected: {self.client_addr}")