"""
UDP Test Utility

A simple UDP client/server testing tool for validating UDP communication.

Description:
    This script provides both UDP server and client modes for testing UDP packet
    transmission and reception. It's useful for testing the udp2tcp converter or
    other UDP-based networking applications.

Usage:
    Server mode (listen for UDP packets):
        python udp_test.py -s 127.0.0.1:5353
        
    Client mode (send UDP packet and wait for response):
        python udp_test.py -c 127.0.0.1:5353 "Hello, Server!"

Server Mode:
    - Listens on the specified host:port for incoming UDP packets
    - Prints received messages and sender information
    - Automatically replies with "OK" acknowledgment to each sender
    - Runs indefinitely until interrupted (Ctrl+C)

Client Mode:
    - Sends a message to the specified UDP server
    - Waits up to 5 seconds for a response
    - Prints the reply received from the server
    - Exits after receiving the response or timeout

Address Format:
    All addresses must be in the format: HOST:PORT
    - HOST: IPv4 address or hostname (e.g., 127.0.0.1, localhost)
    - PORT: Port number 1-65535
    Example: 192.168.1.100:12345

Examples:
    # Start a UDP echo server on localhost:5353
    python udp_test.py -s 127.0.0.1:5353
    
    # In another terminal, send a test message
    python udp_test.py -c 127.0.0.1:5353 "Test message"
    
    # Test the udp2tcp converter
    # Terminal 1: Start the server
    python udp_test.py -s 127.0.0.1:12345
    
    # Terminal 2: Start udp2tcp in UDP-to-TCP mode
    python udp2tcp.py --mode u2t -l 0.0.0.0:8888 -r 127.0.0.1:12345
    
    # Terminal 3: Send a message through the converter
    python udp_test.py -c 127.0.0.1:8888 "Tunneled message"
"""

import argparse
import socket
import sys


def parse_host_port(address: str) -> tuple[str, int]:
	"""
	Parse a HOST:PORT address string into host and port components.
	
	Args:
	    address: Address string in format "HOST:PORT"
	    
	Returns:
	    Tuple of (host, port) where host is a string and port is an integer
	    
	Raises:
	    ValueError: If address format is invalid or port is out of range
	"""
	if ":" not in address:
		raise ValueError(f"Invalid address format: {address}. Expected HOST:PORT")

	host, port_str = address.rsplit(":", 1)
	if not host:
		raise ValueError(f"Invalid address format: {address}. Host is empty")

	try:
		port = int(port_str)
	except ValueError as exc:
		raise ValueError(f"Invalid port in address: {address}") from exc

	if not 1 <= port <= 65535:
		raise ValueError(f"Port out of range in address: {address}")

	return host, port


def run_server(bind_address: str) -> None:
	"""
	Start a UDP server that listens for incoming packets and replies with acknowledgment.
	
	Args:
	    bind_address: Server bind address in format "HOST:PORT"
	    
	The server will:
	- Listen for incoming UDP packets on the specified address
	- Print received messages and sender information
	- Send an "OK" acknowledgment back to each sender
	- Continue running until interrupted (Ctrl+C)
	"""
	host, port = parse_host_port(bind_address)

	with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
		sock.bind((host, port))
		ack_payload = b"OK"
		print(f"UDP server listening on {host}:{port}")
		print("Press Ctrl+C to stop.")

		while True:
			data, addr = sock.recvfrom(65535)
			text = data.decode("utf-8", errors="replace")
			print(f"Received from {addr[0]}:{addr[1]}: {text}")
			sock.sendto(ack_payload, addr)
			print(f"Replied to {addr[0]}:{addr[1]}: OK")


def run_client(target_address: str, message: str) -> None:
	"""
	Send a UDP message to a server and wait for a response.
	
	Args:
	    target_address: Target server address in format "HOST:PORT"
	    message: Message string to send (will be UTF-8 encoded)
	    
	The client will:
	- Send the message to the specified UDP server
	- Wait up to 5 seconds for a response
	- Print the response received from the server
	- Exit after receiving response or timeout
	"""
	host, port = parse_host_port(target_address)
	payload = message.encode("utf-8")

	with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
		sock.settimeout(5.0)
		sent = sock.sendto(payload, (host, port))
		print(f"Sent {sent} bytes to {host}:{port}")
		resp, addr = sock.recvfrom(65535)
		resp_text = resp.decode("utf-8", errors="replace")
		print(f"Received reply from {addr[0]}:{addr[1]}: {resp_text}")


def build_parser() -> argparse.ArgumentParser:
	"""
	Build and return the command-line argument parser.
	
	Returns:
	    ArgumentParser configured with server/client mode options
	"""
	parser = argparse.ArgumentParser(description="Simple UDP client/server tool")
	group = parser.add_mutually_exclusive_group(required=True)
	group.add_argument("-s", "--server", metavar="HOST:PORT", help="Run in server mode")
	group.add_argument("-c", "--client", metavar="HOST:PORT", help="Run in client mode")
	parser.add_argument("message", nargs="?", help="Message to send in client mode")
	return parser


def main() -> int:
	"""
	Main entry point for the UDP test utility.
	
	Returns:
	    Exit code: 0 for success, 1 for errors
	"""
	parser = build_parser()
	args = parser.parse_args()

	try:
		if args.server:
			run_server(args.server)
		else:
			if args.message is None:
				parser.error("message is required in client mode")
			run_client(args.client, args.message)
	except KeyboardInterrupt:
		print("Stopped by user.")
	except Exception as exc:
		print(f"Error: {exc}", file=sys.stderr)
		return 1

	return 0


if __name__ == "__main__":
	raise SystemExit(main())