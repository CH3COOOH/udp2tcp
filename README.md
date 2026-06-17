# UDP2TCP

A bidirectional UDP/TCP converter that allows seamless translation of UDP traffic to TCP and vice versa. This tool uses a length-prefixed framing protocol to encapsulate UDP datagrams over TCP connections, enabling UDP services to communicate through TCP networks.

## Features

- **Bidirectional Conversion**: Convert UDP to TCP (u2t mode) or TCP to UDP (t2u mode)
- **Dual Mode Operation**:
  - **UDP-to-TCP (u2t)**: Listens for UDP packets and forwards them over a TCP connection to a remote server
  - **TCP-to-UDP (t2u)**: Listens for TCP connections and forwards the data to a UDP endpoint
- **Reverse Forwarding**: Automatically relays responses back to the original clients
- **FQDN Support**: Use domain names instead of IP addresses for remote endpoints
- **Multi-threaded**: Handles multiple concurrent packets/connections efficiently with a configurable thread pool
- **Length-Prefixed Protocol**: Uses 4-byte big-endian length prefix for reliable framing

## Installation

### Requirements
- Python 3.6 or higher
- No external dependencies required (uses only Python standard library)

### Setup

1. Clone the repository:
```bash
git clone https://github.com/CH3COOOH/udp2tcp.git
cd udp2tcp
```

## Usage

### Basic Command Format

```bash
python udp2tcp.py --mode {u2t|t2u} -l <listen_host:port> -r <remote_host:port> [--workers N]
```

### Arguments

- `--mode`: Operating mode
  - `u2t`: UDP to TCP converter
  - `t2u`: TCP to UDP converter
- `-l, --listen`: Local endpoint to listen on in format `host:port`
- `-r, --remote`: Remote endpoint in format `host:port` (supports FQDN for TCP targets)
- `--workers`: Thread pool size (default: 8, minimum: 1)

### UDP-to-TCP Conversion (u2t)

Listens for UDP packets on a local address and forwards them over TCP to a remote server. Responses are relayed back to the original UDP clients.

```bash
# Listen on UDP 127.0.0.1:12345 and forward to TCP server at 192.168.1.100:54321
python udp2tcp.py --mode u2t -l 127.0.0.1:12345 -r 192.168.1.100:54321

# Listen on all interfaces with domain name resolution
python udp2tcp.py --mode u2t -l 0.0.0.0:12345 -r example.com:54321
```

### TCP-to-UDP Conversion (t2u)

Listens for TCP connections on a local address and forwards the data to a UDP endpoint. UDP responses are relayed back to the TCP client.

```bash
# Listen on TCP 0.0.0.0:54321 and forward to UDP endpoint at 127.0.0.1:12345
python udp2tcp.py --mode t2u -l 0.0.0.0:54321 -r 127.0.0.1:12345

# Listen on localhost with custom worker pool
python udp2tcp.py --mode t2u -l 127.0.0.1:54321 -r 192.168.1.50:12345 --workers 16
```

## Protocol Details

### Frame Format

The tool uses a length-prefixed TCP framing protocol:

```
[4-byte length][message type][addr type][port][IP address][payload]
```

- **Length**: 4-byte big-endian unsigned integer indicating body length
- **Message Type**: 1 byte
  - `0x01`: UDP to Remote
  - `0x02`: Remote to UDP
- **Address Type**: 1 byte
  - `0x04`: IPv4
  - `0x06`: IPv6 (reserved for future use, not yet implemented)
- **Port**: 2-byte big-endian unsigned integer
- **IP Address**: 4 bytes (IPv4) or 16 bytes (IPv6)
- **Payload**: Variable length UDP data

## Network Considerations

### UDP Packet Size and MTU

When using this tool to forward UDP packets, the payload size is important for network efficiency. Each UDP packet is wrapped with additional headers before transmission over TCP:

```
Standard Ethernet MTU = 1500 bytes
├─ IP Header = 20 bytes
├─ TCP Header = 20 bytes
├─ Frame Header (length-prefixed) = 12 bytes
└─ UDP Payload (your data) = ?
```

**Available space for UDP payload: 1500 - 20 - 20 - 12 = 1448 bytes**

### Recommended UDP Packet Sizes

| Use Case | Recommended Size | Notes |
|----------|------------------|-------|
| Maximum throughput | 1448 bytes | Fits exactly in one MTU, no fragmentation |
| Safe default | 1400 bytes | Leave margin for network variations |
| DNS queries | < 512 bytes | Standard DNS response size, very safe |
| Small packets | < 256 bytes | Minimal overhead risk |

**Best Practice:** Limit UDP payloads to **1400-1450 bytes** to avoid IP fragmentation, which increases latency and packet loss risk.

## Examples

### Example 1: Tunnel UDP through a TCP Network

Use case: Forward local UDP traffic through a TCP tunnel to a remote network.

```bash
# On the tunnel server (receiving TCP, sending to UDP endpoint)
python udp2tcp.py --mode t2u -l 0.0.0.0:8888 -r 192.168.1.100:5353

# On the tunnel client (listening for local UDP, forwarding to TCP server)
python udp2tcp.py --mode u2t -l 127.0.0.1:5353 -r tcp-server.example.com:8888

# Now UDP clients can query DNS on localhost:5353, which tunnels through TCP to the server
dig @127.0.0.1 -p 5353 example.com
```

### Example 2: Load Balancing with Multiple Workers

```bash
# Use more workers for high-traffic scenarios
python udp2tcp.py --mode u2t -l 0.0.0.0:12345 -r backend.internal:9999 --workers 32
```

## Testing

A test script is included to verify the functionality:

```bash
python udp_test.py
```

## Limitations

- **IPv4 Only**: Currently supports IPv4 addresses only. IPv6 support is not yet implemented. All endpoints must be specified using IPv4 addresses or hostnames that resolve to IPv4.

## Troubleshooting

### Connection Refused

- Ensure the remote endpoint is running and accepting connections
- Check firewall rules between local and remote hosts
- Verify the remote host and port are correct

### Port Already in Use

- Change the listen port or kill the existing process using the port
- On Linux: `lsof -i :port` to find the process
- On Windows: `netstat -ano | findstr :port` to find the process

### High CPU Usage

- Reduce the number of workers if not needed
- Check if there's an issue with the remote endpoint causing reconnection loops

## Architecture

The converter uses:
- **Threading**: Multi-threaded packet handling for concurrent operations
- **Connection Pooling**: Maintains persistent TCP connections or UDP flows
- **Auto-reconnection**: Automatically reconnects on TCP failures
- **Frame-based Protocol**: Length-prefixed framing ensures reliable message boundaries

## License

See the LICENSE file for details.

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## Author

Created as a utility for tunneling UDP services over TCP networks.