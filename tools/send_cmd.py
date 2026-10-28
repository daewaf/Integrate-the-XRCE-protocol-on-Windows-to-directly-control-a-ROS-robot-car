"""向 agent 的本地控制口发送运动指令：python send_cmd.py <linear> <angular> <seconds>"""
import socket
import sys


def main():
    line = " ".join(sys.argv[1:]) or "0 0 0.2"
    sock = socket.create_connection(("127.0.0.1", 8898), timeout=3)
    sock.sendall((line + "\n").encode())
    print(sock.recv(128).decode().strip())


if __name__ == "__main__":
    main()
