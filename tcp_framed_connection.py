import threading
import socket

from socket_util import resolve_address, read_frame
from debug import debug


class TcpFramedConnection:
	"""
	Managed TCP connection for bidirectional framed communication.
	
	Handles connection establishment, frame reading/writing, and automatic
	reconnection with proper locking for thread-safe operations.
	"""
	
	def __init__(self, host, port):
		"""
		Initialize a framed TCP connection.
		
		Args:
		    host: Remote host to connect to
		    port: Remote port to connect to
		"""
		self.host = host
		self.port = port
		self.sock = None
		self.state_lock = threading.Lock()
		self.send_lock = threading.Lock()

	def _reset_locked(self):
		"""
		Close and reset the socket (internal method, must be called with state_lock).
		"""
		if self.sock is not None:
			debug(f"[TcpFramedConnection] Resetting/closing connection to {self.host}:{self.port}")
			try:
				self.sock.close()
			except OSError:
				pass
			self.sock = None

	def _ensure_connected_locked(self):
		"""
		Ensure a connection is established (internal method, must be called with state_lock).
		
		Returns:
		    The connected socket
		"""
		if self.sock is not None:
			return self.sock

		family, socktype, proto, _, sockaddr = resolve_address(
			self.host, self.port, socket.SOCK_STREAM
		)
		debug(f"[TcpFramedConnection] Connecting to {self.host}:{self.port}")
		sock = socket.socket(family, socktype, proto)
		sock.connect(sockaddr)
		# Disable Nagle for lower latency where appropriate
		sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
		self.sock = sock
		debug(f"[TcpFramedConnection] Connected to {self.host}:{self.port}")
		return sock

	def send_frame(self, frame):
		"""
		Send a complete frame with automatic reconnection on failure.
		
		Args:
		    frame: Complete frame bytes to send
		    
		Raises:
		    OSError: If connection and reconnection both fail
		"""
		with self.send_lock:
			for attempt in range(2):
				try:
					with self.state_lock:
						sock = self._ensure_connected_locked()
					debug(f"[TcpFramedConnection] Sending frame {len(frame)} bytes (attempt {attempt+1}) to {self.host}:{self.port}")
					sock.sendall(frame)
					return
				except OSError as exc:
					debug(f"[TcpFramedConnection] Send failed (attempt {attempt+1}): {exc}")
					with self.state_lock:
						self._reset_locked()
					if attempt == 1:
						raise

	def read_frame(self):
		"""
		Read a frame from the remote server with automatic reconnection on failure.
		
		Returns:
		    Frame body bytes
		    
		Raises:
		    OSError: On persistent connection failures
		"""
		while True:
			with self.state_lock:
				sock = self._ensure_connected_locked()
			try:
				frame = read_frame(sock)
				if frame is None:
					debug(f"[TcpFramedConnection] Peer closed connection {self.host}:{self.port}")
					raise OSError("TCP peer closed")
				return frame
			except OSError as exc:
				debug(f"[TcpFramedConnection] Read error: {exc}, resetting and retrying")
				with self.state_lock:
					self._reset_locked()

	def close(self):
		"""
		Close the connection.
		"""
		with self.state_lock:
			debug(f"[TcpFramedConnection] Closing connection to {self.host}:{self.port}")
			self._reset_locked()

