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
import sys

from converter import UTConverter
from debug import set_debug
from socket_util import parse_endpoint


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
	parser.add_argument(
		"-k",
		"--key",
		dest="key",
		help="Password for ChaCha20-Poly1305 encryption",
	)
	parser.add_argument(
		"--debug",
		action="store_true",
		help="Enable debug logging",
	)
	return parser

def init_cipher(key):
	from utc_crypto import Crypto
	cipher = Crypto()
	if cipher.ensure_crypto_available() is None:
		raise RuntimeError("Cryptography library is not available")
		sys.exit(1)
	encryption_key = cipher.derive_key_from_password(key)
	print("[crypto] ChaCha20-Poly1305 encryption enabled")
	return cipher


def main():
	"""
	Main entry point for the UDP2TCP converter.
	
	Parses command-line arguments and starts either UDP-to-TCP or TCP-to-UDP
	conversion mode based on the --mode argument.
	"""
	parser = build_parser()
	args = parser.parse_args()
	crypto = None

	if args.workers < 1:
		parser.error("--workers must be greater than or equal to 1")

	if args.key is not None:
		crypto = init_cipher(args.key)

	set_debug(args.debug)
	local_host, local_port = args.listen
	remote_host, remote_port = args.remote

	converter = UTConverter(
		mode=args.mode,
		listen=(local_host, local_port),
		remote=(remote_host, remote_port),
		workers=args.workers,
		cipher=crypto if args.key is not None else None,
		debug=args.debug
	)
	converter.run()


if __name__ == "__main__":
	main()
