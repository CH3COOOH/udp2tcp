import argparse
import ipaddress
import socket
import struct
from const import *
from debug import debug

def log(msg):
	print("[socket_util]" + msg)

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

def reset_tcp_connection(sock):
	"""
	Force immediate TCP connection reset.
	"""
	try:
		sock.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack('ii', 1, 0))
		log(f"Socket SO_LINGER set to force reset")
	except OSError:
		pass
	try:
		sock.close()
	except OSError:
		pass

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
	if body_len > MAX_FRAME_SIZE:
		raise ValueError(f"[socket_util] Frame too large: {body_len} bytes")
	return recv_exact(sock, body_len)


def pack_datagram_frame(msg_type, endpoint, payload, cipher=None):
	host, port = endpoint
	ip_obj = ipaddress.ip_address(host)
	if ip_obj.version == 4:
		addr_type = ADDR_TYPE_IPV4
	else:
		addr_type = ADDR_TYPE_IPV6
	packed_ip = ip_obj.packed
	body = struct.pack("!BBH", msg_type, addr_type, port) + packed_ip + payload
	if cipher is not None:
		body = cipher.encrypt_frame_body(body)
		debug(f"[socket_util] Encrypted frame body: {body.hex()}")
	return struct.pack("!I", len(body)) + body


def unpack_datagram_frame(frame_body, cipher=None):
	if cipher is not None:
		frame_body = cipher.decrypt_frame_body(frame_body)
		if frame_body is None:
			raise ValueError("[socket_util] Decryption failed or nonce reuse detected")
		debug(f"[socket_util] Decrypted frame body: {frame_body.hex()}")
	if len(frame_body) < 4:
		raise ValueError("[socket_util] Frame is too short")

	msg_type, addr_type, port = struct.unpack("!BBH", frame_body[:4])
	if addr_type == ADDR_TYPE_IPV4:
		addr_len = 4
	elif addr_type == ADDR_TYPE_IPV6:
		addr_len = 16
	else:
		raise ValueError(f"[socket_util] Unsupported address type: {addr_type}")

	if len(frame_body) < 4 + addr_len:
		raise ValueError("[socket_util] Frame address section is incomplete")

	host_raw = frame_body[4 : 4 + addr_len]
	host = str(ipaddress.ip_address(host_raw))
	payload = frame_body[4 + addr_len :]
	return msg_type, (host, port), payload