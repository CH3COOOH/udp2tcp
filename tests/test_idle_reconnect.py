import socket
import time
import subprocess
import threading

# This script assumes the following processes are running (started earlier in the session):
# - UDP echo server bound to 127.0.0.1:5000 (tools/udp_txrx.py -s)
# - t2u converter listening on 0.0.0.0:4999 forwarding to 127.0.0.1:5000
# - u2t converter listening on 0.0.0.0:14999 forwarding to 127.0.0.1:4999

SERVER = ('127.0.0.1', 14999)

def send_and_recv(msg):
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.settimeout(5)
        s.sendto(msg.encode(), SERVER)
        try:
            resp, addr = s.recvfrom(65535)
            print('recv:', resp.decode(), 'from', addr)
            return True
        except socket.timeout:
            print('timeout waiting for reply')
            return False

if __name__ == '__main__':
    print('Send initial message')
    ok1 = send_and_recv('first')
    print('Sleeping 65s to trigger idle close in u2t')
    time.sleep(65)
    print('Send after idle')
    ok2 = send_and_recv('second')
    print('Results:', ok1, ok2)
