start python ..\udp2tcp.py --mode t2u -l 127.0.0.1:5199 -r 127.0.0.1:5100
start python ..\udp2tcp.py --mode u2t -l 0.0.0.0:5098 -r 127.0.0.1:5199
start python ..\tools\udp_txrx.py -s 127.0.0.1:5100
