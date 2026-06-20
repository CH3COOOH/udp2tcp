import threading
import socket
import struct

from socket_util import resolve_address
from debug import debug

class TcpPacketSender:
	"""
	Simple TCP client for sending raw packets to a remote server.
	
	Automatic reconnection is attempted on connection failures.
	"""
	
	def __init__(self, host, port):
		"""
		Initialize a TCP packet sender.
		
		Args:
		    host: Remote host to connect to
		    port: Remote port to connect to
		"""
		self.host = host
		self.port = port
		self.sock = None
		self.lock = threading.Lock()

	def _connect_locked(self):
		"""
		Ensure a connection is established (internal method, must be called with lock).
		"""
		if self.sock is not None:
			return

		family, socktype, proto, _, sockaddr = resolve_address(
			self.host, self.port, socket.SOCK_STREAM
		)
		debug(f"[TcpPacketSender] Connecting to {self.host}:{self.port}")
		sock = socket.socket(family, socktype, proto)
		sock.connect(sockaddr)
		# Disable Nagle for lower latency where appropriate
		sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
		self.sock = sock
		debug(f"[TcpPacketSender] Connected to {self.host}:{self.port}")

	def send_packet(self, payload):
		"""
		Send a packet to the remote server with automatic reconnection on failure.
		
		Args:
		    payload: Raw packet data to send
		    
		Raises:
		    OSError: If connection and reconnection both fail
		"""
		frame = struct.pack("!I", len(payload)) + payload

		with self.lock:
			for attempt in range(2):
				try:
					self._connect_locked()
					debug(f"[TcpPacketSender] Sending {len(payload)} bytes (attempt {attempt+1}) to {self.host}:{self.port}")
					self.sock.sendall(frame)
					return
				except OSError as exc:
					debug(f"[TcpPacketSender] Send failed (attempt {attempt+1}): {exc}")
					if self.sock is not None:
						try:
							self.sock.close()
						except OSError:
							pass
						self.sock = None
					if attempt == 1:
						raise

	def close(self):
		"""
		Close the connection.
		"""
		with self.lock:
			if self.sock is not None:
				debug(f"[TcpPacketSender] Closing connection to {self.host}:{self.port}")
				try:
					self.sock.close()
				finally:
					self.sock = None
