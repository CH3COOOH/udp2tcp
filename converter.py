from concurrent.futures import ThreadPoolExecutor
import ipaddress
import socket
import struct
import threading
import time

from const import *
from tcp_framed_connection import TcpFramedConnection
from tcp_client_handler import TcpClientHandler
import socket_util

class UTConverter:
	def __init__(self, mode, listen, remote, workers=8, cipher=None, debug=False):
		self.mode = mode
		self.listen = listen
		self.remote = remote
		self.workers = workers
		self.cipher = cipher
		self.debug = debug

	def forward_udp_packet(self, tunnel, payload, client_addr):
		"""
		Forward a single UDP packet to the remote TCP server.
		
		Args:
			tunnel: TcpFramedConnection to send through
			payload: UDP packet payload
			client_addr: UDP client address (host, port)
		"""
		try:
			print(f"[u2t] forward_udp_packet: received {len(payload)} bytes from {client_addr}")
			frame = socket_util.pack_datagram_frame(MSG_UDP_TO_REMOTE, client_addr, payload, cipher=self.cipher)
			tunnel.send_frame(frame)
			print(f"[u2t] {client_addr} -> TCP, {len(payload)} bytes")
		except OSError as exc:
			print(f"[u2t] Forwarding failed for {client_addr}: {exc}")
			time.sleep(10)  # Avoid tight loop on persistent errors

	
	def u2t_reverse_loop(self, tunnel, udp_sock, stop_event):
		"""
		Handle reverse forwarding for UDP-to-TCP mode.
		
		Reads responses from the remote TCP server and sends them back to the
		original UDP clients.
		
		Args:
			tunnel: TcpFramedConnection to read responses from
			udp_sock: UDP socket to send responses back to clients
			stop_event: Threading event to signal shutdown
		"""
		while not stop_event.is_set():
			try:
				frame_body = tunnel.read_frame()
				msg_type, client_endpoint, payload = socket_util.unpack_datagram_frame(frame_body, cipher=self.cipher)
				if msg_type != MSG_REMOTE_TO_UDP:
					print(f"[u2t] Ignoring unknown frame type: {msg_type}")
					continue
				udp_sock.sendto(payload, client_endpoint)
				print(f"[u2t] TCP -> {client_endpoint}, {len(payload)} bytes")
			except (OSError, ValueError) as exc:
				if stop_event.is_set():
					return
				print(f"[u2t] Reverse relay error: {exc}")
				time.sleep(10)  # Avoid tight loop on persistent errors

	def run_udp_to_tcp(self, workers):
		"""
		Run UDP-to-TCP conversion mode.
		
		Listens for UDP packets on local_host:local_port and forwards them over TCP
		to remote_host:remote_port. Automatically relays responses back to UDP clients.
		
		Args:
			local_host: Local address to listen on
			local_port: Local UDP port
			remote_host: Remote TCP server host
			remote_port: Remote TCP server port
			workers: Thread pool size for handling packets
		"""
		udp_sock = socket_util.create_bound_socket(self.listen[0], self.listen[1], socket.SOCK_DGRAM)
		tunnel = TcpFramedConnection(self.remote[0], self.remote[1])
		stop_event = threading.Event()

		print(f"[u2t] Listening for UDP on {self.listen[0]}:{self.listen[1]}")
		print(f"[u2t] Forwarding to TCP target {self.remote[0]}:{self.remote[1]}")
		print("[u2t] Reverse forwarding enabled: remote UDP replies will be relayed back")

		reader = threading.Thread(
			target=self.u2t_reverse_loop,
			args=(tunnel, udp_sock, stop_event),
			daemon=True,
		)
		reader.start()

		with udp_sock, ThreadPoolExecutor(max_workers=workers) as executor:
			try:
				while True:
					try:
						payload, client_addr = udp_sock.recvfrom(BUFFER_SIZE)
					except ConnectionResetError:
						# Ignore ICMP "port unreachable" on Windows which maps to
						# WSAECONNRESET (10054). Continue listening for other packets.
						continue
					print(f"[u2t] recvfrom: got {len(payload)} bytes from {client_addr}")
					executor.submit(self.forward_udp_packet, tunnel, payload, client_addr)
			except KeyboardInterrupt:
				print("\n[u2t] Shutdown signal received, closing")
			finally:
				stop_event.set()
				tunnel.close()

	def run_tcp_to_udp(self, workers):
		"""
		Run TCP-to-UDP conversion mode.
		
		Listens for TCP connections on local_host:local_port and forwards the data
		to remote_host:remote_port over UDP. Automatically relays UDP responses
		back to TCP clients.
		
		Args:
			local_host: Local address to listen on
			local_port: Local TCP port
			remote_host: Remote UDP server host
			remote_port: Remote UDP server port
			workers: Thread pool size for handling connections
		"""
		tcp_sock = socket_util.create_bound_socket(self.listen[0], self.listen[1], socket.SOCK_STREAM)
		udp_family, _, _, _, udp_target = socket_util.resolve_address(
			self.remote[0], self.remote[1], socket.SOCK_DGRAM
		)

		tcp_sock.listen()
		print(f"[t2u] Listening for TCP on {self.listen[0]}:{self.listen[1]}")
		print(f"[t2u] Forwarding to UDP target {self.remote[0]}:{self.remote[1]}")
		print("[t2u] Reverse forwarding enabled: UDP replies will be relayed to TCP")

		with tcp_sock, ThreadPoolExecutor(max_workers=workers) as executor:
			try:
				while True:
					try:
						conn, client_addr = tcp_sock.accept()
					except OSError as exc:
						print(f"[t2u] Accept failed: {exc}")
						continue
					handler = TcpClientHandler(conn, client_addr, udp_family, udp_target, cipher=self.cipher)
					executor.submit(handler.run)
			except KeyboardInterrupt:
				print("\n[t2u] Shutdown signal received, closing")
	
	def run(self):
		if self.mode == "u2t":
			self.run_udp_to_tcp(self.workers)
		else:
			self.run_tcp_to_udp(self.workers)