import threading
import socket

from socket_util import resolve_address, read_frame, reset_tcp_connection
from debug import debug
import traceback


def log(msg):
	print("[tcp_framed_connection] " + msg)


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
			# Log stack to help identify who requested the reset
			st = ''.join(traceback.format_stack(limit=6))
			debug(f"[TcpFramedConnection] _reset_locked call stack:\n{st}")

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
		# Set a short read timeout so a dead peer is detected promptly
		try:
			# use configured timeout if provided on the object or fall back to 10s
			timeout = getattr(self, 'tcp_timeout', 10.0)
			sock.settimeout(timeout)
		except OSError:
			pass
		# Enable TCP keepalive where available to help detect broken connections
		try:
			sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
			# Platform-specific keepalive tuning (best-effort)
			if hasattr(socket, 'TCP_KEEPIDLE'):
				sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPIDLE, 30)
			if hasattr(socket, 'TCP_KEEPINTVL'):
				sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPINTVL, 10)
			if hasattr(socket, 'TCP_KEEPCNT'):
				sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPCNT, 3)
		except OSError:
			# Non-fatal if options aren't supported
			pass
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

	def read_frame(self, reconnect=True):
		"""
		Read a frame from the remote server.
		
		If reconnect is True, the connection will be established or reestablished
		automatically. If reconnect is False, an existing connection is required.
		
		Returns:
			Frame body bytes
			
		Raises:
			OSError: On persistent connection failures
			ConnectionResetError: When no active connection exists or the remote closes
		"""
		while True:
			with self.state_lock:
				if reconnect:
					sock = self._ensure_connected_locked()
				else:
					if self.sock is None:
						raise ConnectionResetError("No active TCP connection")
					sock = self.sock
			try:
				try:
					frame = read_frame(sock)
				except socket.timeout:
					# Non-fatal: no data available yet. If reconnecting, loop and retry.
					if reconnect:
						continue
					# If not reconnecting, propagate as connection reset
					raise ConnectionResetError("TCP read timed out")
				if frame is None:
					log(f"Peer closed/reset connection {self.host}:{self.port}")
					debug(f"[TcpFramedConnection] Peer closed/reset connection {self.host}:{self.port}")
					raise ConnectionResetError("TCP peer closed/reset")
				return frame
			except ConnectionResetError as exc:
				log(f"TCP reset detected: {exc}, resetting and retrying")
				debug(f"[TcpFramedConnection] TCP reset detected, resetting and retrying. Error:\n{exc}")
				with self.state_lock:
					self._reset_locked()
				if reconnect:
					continue
				raise
			except OSError as exc:
				log(f"Read error: {exc}, resetting and retrying")
				debug(f"[TcpFramedConnection] Read error, resetting and retrying. Error:\n{exc}")
				with self.state_lock:
					self._reset_locked()
				if reconnect:
					continue
				raise

	def close(self):
		"""
		Close the connection.
		"""
		with self.state_lock:
			debug(f"[TcpFramedConnection] Closing connection to {self.host}:{self.port}")
			self._reset_locked()

	def is_connected(self):
		"""Return True when a TCP socket is currently open."""
		with self.state_lock:
			return self.sock is not None

	def reset(self):
		"""
		Force a TCP reset for the current connection.
		"""
		with self.state_lock:
			if self.sock is not None:
				debug(f"[TcpFramedConnection] Resetting connection to {self.host}:{self.port}")
				# force TCP reset at OS level
				try:
					reset_tcp_connection(self.sock)
				except Exception as e:
					debug(f"[TcpFramedConnection] reset_tcp_connection failed: {e}")
				self.sock = None
				# Log stack to help diagnose who initiated reset
				st = ''.join(traceback.format_stack(limit=6))
				debug(f"[TcpFramedConnection] reset() call stack:\n{st}")

