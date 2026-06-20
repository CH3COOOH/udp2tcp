import socket
import threading
import time
from converter import UTConverter
from utc_crypto import Crypto

LISTEN = ('127.0.0.1', 55000)
REMOTE = ('127.0.0.1', 55001)

# dummy UDP target to satisfy t2u run
udp_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
udp_sock.bind(REMOTE)

def start_server():
    crypto = Crypto()
    crypto.derive_key_from_password('correct_password')
    converter = UTConverter(mode='t2u', listen=LISTEN, remote=REMOTE, workers=1, cipher=crypto)
    converter.run()

server_thread = threading.Thread(target=start_server, daemon=True)
server_thread.start()

time.sleep(1)

# Connect raw TCP and send invalid encrypted frame body
client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
client.connect(LISTEN)
# send length 1 + invalid payload
client.sendall((4).to_bytes(4, 'big') + b'bad!')

# wait for server to reset
client.settimeout(5)
try:
    data = client.recv(1024)
    print('recv:', data)
except Exception as exc:
    print('recv exception:', exc)
finally:
    client.close()
    udp_sock.close()
