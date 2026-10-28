"""验证控制口支持一条 TCP 连接连续发送多条指令。"""
import socket
import time

sock = socket.create_connection(("127.0.0.1", 8898), timeout=3)
for cmd in ("0.03 0 0.2", "0 0.2 0.2", "0 0 0.2"):
    sock.sendall((cmd + "\n").encode())
    print(sock.recv(64).decode().strip())
    time.sleep(0.3)
sock.close()
print("multi-line OK")
