"""向主控板发送 XRCE RESET，尝试复位卡住的会话。"""
import os
import socket
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from xrce.frame import FLAG_ENDIANNESS, STREAM_NONE, Message, Submessage, SUB_RESET

CLIENT_IP = "10.251.213.55"
PORT = 8888


def main():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("0.0.0.0", PORT))
    for session in (0x81, 0x80):
        msg = Message(session, STREAM_NONE, 0,
                      [Submessage(SUB_RESET, b"", FLAG_ENDIANNESS)])
        sock.sendto(msg.encode(), (CLIENT_IP, PORT))
        print("sent RESET session", hex(session))
        time.sleep(0.2)


if __name__ == "__main__":
    main()
