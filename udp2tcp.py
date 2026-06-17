"""
UDP2TCP Bidirectional Converter

A tool for converting UDP traffic to TCP and vice versa using a length-prefixed
framing protocol. Supports two modes:
- u2t (UDP-to-TCP): Listen for UDP packets and forward them over TCP
- t2u (TCP-to-UDP): Listen for TCP connections and forward data to UDP

The tool maintains bidirectional communication with automatic reverse forwarding
to relay responses back to original clients.
"""

import argparse
import ipaddress
import socket
import struct
import threading
from concurrent.futures import ThreadPoolExecutor


BUFFER_SIZE = 65535
FRAME_HEADER_SIZE = 4
MSG_UDP_TO_REMOTE = 1
MSG_REMOTE_TO_UDP = 2
ADDR_TYPE_IPV4 = 4
ADDR_TYPE_IPV6 = 6


def parse_endpoint(value):
	"""
	Parse and validate an endpoint string in host:port format.
	
	Args:
	    value: Endpoint string in format "host:port"
	    
	Returns:
	    Tuple of (host, port) where host is a string and port is an integer
	    
	Raises:
	    argparse.ArgumentTypeError: If format is invalid or port is out of range
	"""
	host, separator, port_text = value.rpartition(":")
	if not separator or not host or not port_text:
		raise argparse.ArgumentTypeError(
			"Endpoint must use the format host:port, for example 127.0.0.1:12345"
		)

	try:
		port = int(port_text)
	except ValueError as exc:
		raise argparse.ArgumentTypeError("Port must be an integer") from exc

	if not 0 < port < 65536:
		raise argparse.ArgumentTypeError("Port must be in the range 1-65535")

	return host, port


def resolve_address(host, port, socktype, passive=False):
	"""
	Resolve a host:port address to a socket address using getaddrinfo.
	
	Args:
	    host: Hostname or IP address to resolve
	    port: Port number
	    socktype: Socket type (socket.SOCK_STREAM or socket.SOCK_DGRAM)
	    passive: If True, use AI_PASSIVE flag for binding; otherwise for connecting
	    
	Returns:
	    Tuple of (family, socktype, proto, canonname, sockaddr)
	    
	Raises:
	    OSError: If address resolution fails
	"""
	flags = socket.AI_PASSIVE if passive else 0
	infos = socket.getaddrinfo(host, port, socket.AF_UNSPEC, socktype, 0, flags)
	if not infos:
		raise OSError(f"Unable to resolve address: {host}:{port}")
	return infos[0]


def create_bound_socket(host, port, socktype):
	"""
	Create and bind a socket to the specified host and port.
	
	Args:
	    host: Hostname or IP address to bind to
	    port: Port number to bind to
	    socktype: Socket type (socket.SOCK_STREAM or socket.SOCK_DGRAM)
	    
	Returns:
	    A bound socket object
	    
	Note:
	    For TCP sockets, SO_REUSEADDR is set to allow quick rebinding.
	"""
	family, socktype, proto, _, sockaddr = resolve_address(
		host, port, socktype, passive=True
	)
	sock = socket.socket(family, socktype, proto)
	if socktype == socket.SOCK_STREAM:
		sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
	sock.bind(sockaddr)
	return sock


def recv_exact(sock, size):
	"""
	Receive exactly the specified number of bytes from a socket.
	
	Args:
	    sock: Socket to receive from
	    size: Number of bytes to receive
	    
	Returns:
	    Bytes of exactly the requested size, or None if connection closed
	    
	Note:
	    Blocks until all bytes are received or connection is closed.
	"""
	chunks = bytearray()
	while len(chunks) < size:
		chunk = sock.recv(size - len(chunks))
		if not chunk:
			return None
		chunks.extend(chunk)
	return bytes(chunks)


def read_frame(sock):
	"""
	Read a complete length-prefixed frame from a TCP socket.
	
	Args:
	    sock: TCP socket to read from
	    
	Returns:
	    Frame body bytes, empty bytes if frame is empty, or None if connection closed
	    
	Frame Format:
	    [4-byte big-endian length][body data]
	"""
	header = recv_exact(sock, FRAME_HEADER_SIZE)
	if header is None:
		return None
	body_len = struct.unpack("!I", header)[0]
	if body_len == 0:
		return b""
	return recv_exact(sock, body_len)


def normalize_endpoint(addr):
	"""
	Normalize an endpoint tuple to (host, port) format.
	
	Args:
	    addr: Address tuple (typically from recvfrom)
	    
	Returns:
	    Tuple of (host, port)
	"""
	return addr[0], addr[1]


def pack_datagram_frame(msg_type, endpoint, payload):
	"""
	Pack a UDP datagram into a length-prefixed frame for TCP transmission.
	
	Args:
	    msg_type: Message type (MSG_UDP_TO_REMOTE or MSG_REMOTE_TO_UDP)
	    endpoint: Tuple of (host, port) representing the UDP address
	    payload: Raw UDP payload data
	    
	Returns:
	    Complete frame bytes ready to send over TCP
	    
	Frame Format:
	    [4-byte length][message_type][addr_type][port][IP_address][payload]
	"""
	host, port = normalize_endpoint(endpoint)
	ip_obj = ipaddress.ip_address(host)
	if ip_obj.version == 4:
		addr_type = ADDR_TYPE_IPV4
	else:
		addr_type = ADDR_TYPE_IPV6
	packed_ip = ip_obj.packed
	body = struct.pack("!BBH", msg_type, addr_type, port) + packed_ip + payload
	return struct.pack("!I", len(body)) + body


def unpack_datagram_frame(frame_body):
	"""
	Unpack a UDP datagram from a length-prefixed frame.
	
	Args:
	    frame_body: Frame body bytes (without length prefix)
	    
	Returns:
	    Tuple of (msg_type, (host, port), payload)
	    
	Raises:
	    ValueError: If frame format is invalid or incomplete
	"""
	if len(frame_body) < 4:
		raise ValueError("Frame is too short")

	msg_type, addr_type, port = struct.unpack("!BBH", frame_body[:4])
	if addr_type == ADDR_TYPE_IPV4:
		addr_len = 4
	elif addr_type == ADDR_TYPE_IPV6:
		addr_len = 16
	else:
		raise ValueError(f"Unsupported address type: {addr_type}")

	if len(frame_body) < 4 + addr_len:
		raise ValueError("Frame address section is incomplete")

	host_raw = frame_body[4 : 4 + addr_len]
	host = str(ipaddress.ip_address(host_raw))
	payload = frame_body[4 + addr_len :]
	return msg_type, (host, port), payload


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
		sock = socket.socket(family, socktype, proto)
		sock.connect(sockaddr)
		self.sock = sock

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
					self.sock.sendall(frame)
					return
				except OSError:
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
				try:
					self.sock.close()
				finally:
					self.sock = None


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
		sock = socket.socket(family, socktype, proto)
		sock.connect(sockaddr)
		self.sock = sock
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
					sock.sendall(frame)
					return
				except OSError:
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
					raise OSError("TCP peer closed")
				return frame
			except OSError:
				with self.state_lock:
					self._reset_locked()

	def close(self):
		"""
		Close the connection.
		"""
		with self.state_lock:
			self._reset_locked()


def run_udp_to_tcp(local_host, local_port, remote_host, remote_port, workers):
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
	udp_sock = create_bound_socket(local_host, local_port, socket.SOCK_DGRAM)
	tunnel = TcpFramedConnection(remote_host, remote_port)
	stop_event = threading.Event()

	print(f"[u2t] Listening for UDP on {local_host}:{local_port}")
	print(f"[u2t] Forwarding to TCP target {remote_host}:{remote_port}")
	print("[u2t] Reverse forwarding enabled: remote UDP replies will be relayed back")

	reader = threading.Thread(
		target=u2t_reverse_loop,
		args=(tunnel, udp_sock, stop_event),
		daemon=True,
	)
	reader.start()

	with udp_sock, ThreadPoolExecutor(max_workers=workers) as executor:
		try:
			while True:
				payload, client_addr = udp_sock.recvfrom(BUFFER_SIZE)
				executor.submit(forward_udp_packet, tunnel, payload, client_addr)
		except KeyboardInterrupt:
			print("\n[u2t] Shutdown signal received, closing")
		finally:
			stop_event.set()
			tunnel.close()


def u2t_reverse_loop(tunnel, udp_sock, stop_event):
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
			msg_type, client_endpoint, payload = unpack_datagram_frame(frame_body)
			if msg_type != MSG_REMOTE_TO_UDP:
				print(f"[u2t] Ignoring unknown frame type: {msg_type}")
				continue
			udp_sock.sendto(payload, client_endpoint)
			print(f"[u2t] TCP -> {client_endpoint}, {len(payload)} bytes")
		except (OSError, ValueError) as exc:
			if stop_event.is_set():
				return
			print(f"[u2t] Reverse relay error: {exc}")


def forward_udp_packet(tunnel, payload, client_addr):
	"""
	Forward a single UDP packet to the remote TCP server.
	
	Args:
	    tunnel: TcpFramedConnection to send through
	    payload: UDP packet payload
	    client_addr: UDP client address (host, port)
	"""
	try:
		frame = pack_datagram_frame(MSG_UDP_TO_REMOTE, client_addr, payload)
		tunnel.send_frame(frame)
		print(f"[u2t] {client_addr} -> TCP, {len(payload)} bytes")
	except OSError as exc:
		print(f"[u2t] Forwarding failed for {client_addr}: {exc}")


def run_tcp_to_udp(local_host, local_port, remote_host, remote_port, workers):
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
	tcp_sock = create_bound_socket(local_host, local_port, socket.SOCK_STREAM)
	udp_family, _, _, _, udp_target = resolve_address(
		remote_host, remote_port, socket.SOCK_DGRAM
	)

	tcp_sock.listen()
	print(f"[t2u] Listening for TCP on {local_host}:{local_port}")
	print(f"[t2u] Forwarding to UDP target {remote_host}:{remote_port}")
	print("[t2u] Reverse forwarding enabled: UDP replies will be relayed to TCP")

	with tcp_sock, ThreadPoolExecutor(max_workers=workers) as executor:
		try:
			while True:
				conn, client_addr = tcp_sock.accept()
				executor.submit(
					handle_tcp_client,
					conn,
					client_addr,
					udp_family,
					udp_target,
				)
		except KeyboardInterrupt:
			print("\n[t2u] Shutdown signal received, closing")


def handle_tcp_client(conn, client_addr, udp_family, udp_target):
	"""
	Handle a single TCP client connection in TCP-to-UDP mode.
	
	Reads framed messages from the TCP client, creates UDP flows to the remote
	server, and handles bidirectional communication.
	
	Args:
	    conn: TCP socket connected to the client
	    client_addr: Client address (host, port)
	    udp_family: Socket family for UDP (AF_INET or AF_INET6)
	    udp_target: Remote UDP server address tuple
	"""
	print(f"[t2u] TCP client connected: {client_addr}")
	stop_event = threading.Event()
	flow_lock = threading.Lock()
	flows = {}
	send_lock = threading.Lock()

	def send_back_to_tcp(endpoint, payload):
		frame = pack_datagram_frame(MSG_REMOTE_TO_UDP, endpoint, payload)
		with send_lock:
			conn.sendall(frame)

	def reply_reader(endpoint, flow_sock):
		while not stop_event.is_set():
			try:
				payload = flow_sock.recv(BUFFER_SIZE)
				if not payload:
					break
				send_back_to_tcp(endpoint, payload)
				print(f"[t2u] UDP {udp_target} -> TCP, {len(payload)} bytes for {endpoint}")
			except OSError:
				break

	def get_or_create_flow(endpoint):
		with flow_lock:
			flow = flows.get(endpoint)
			if flow is not None:
				return flow

			flow_sock = socket.socket(udp_family, socket.SOCK_DGRAM)
			flow_sock.connect(udp_target)
			thread = threading.Thread(
				target=reply_reader,
				args=(endpoint, flow_sock),
				daemon=True,
			)
			thread.start()
			flows[endpoint] = (flow_sock, thread)
			return flows[endpoint]

	with conn:
		try:
			while True:
				frame_body = read_frame(conn)
				if frame_body is None:
					break
				msg_type, endpoint, payload = unpack_datagram_frame(frame_body)
				if msg_type != MSG_UDP_TO_REMOTE:
					print(f"[t2u] Ignoring unknown frame type: {msg_type}")
					continue

				flow_sock, _ = get_or_create_flow(endpoint)
				flow_sock.send(payload)
				print(f"[t2u] TCP {endpoint} -> UDP {udp_target}, {len(payload)} bytes")
		except (OSError, ValueError) as exc:
			print(f"[t2u] Client handling failed for {client_addr}: {exc}")
		finally:
			stop_event.set()
			with flow_lock:
				for flow_sock, _thread in flows.values():
					try:
						flow_sock.close()
					except OSError:
						pass
				flows.clear()
			print(f"[t2u] TCP client disconnected: {client_addr}")


def build_parser():
	"""
	Build and return the command-line argument parser.
	
	Returns:
	    ArgumentParser configured for UDP2TCP converter
	"""
	parser = argparse.ArgumentParser(
		description="Bidirectional UDP/TCP converter using a length-prefixed TCP stream"
	)
	parser.add_argument(
		"--mode",
		required=True,
		choices=("u2t", "t2u"),
		help="u2t converts UDP to TCP, t2u converts TCP to UDP",
	)
	parser.add_argument(
		"-l",
		"--listen",
		required=True,
		type=parse_endpoint,
		help="Local listen endpoint in host:port format",
	)
	parser.add_argument(
		"-r",
		"--remote",
		required=True,
		type=parse_endpoint,
		help="Remote endpoint in host:port format, supports FQDN",
	)
	parser.add_argument(
		"--workers",
		type=int,
		default=8,
		help="Thread pool size, default is 8",
	)
	return parser


def main():
	"""
	Main entry point for the UDP2TCP converter.
	
	Parses command-line arguments and starts either UDP-to-TCP or TCP-to-UDP
	conversion mode based on the --mode argument.
	"""
	parser = build_parser()
	args = parser.parse_args()

	if args.workers < 1:
		parser.error("--workers must be greater than or equal to 1")

	local_host, local_port = args.listen
	remote_host, remote_port = args.remote

	if args.mode == "u2t":
		run_udp_to_tcp(local_host, local_port, remote_host, remote_port, args.workers)
		return

	run_tcp_to_udp(local_host, local_port, remote_host, remote_port, args.workers)


if __name__ == "__main__":
	main()
