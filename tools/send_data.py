"""直接向主控板 DataReader 下发 Twist（绕过 agent，用于当前会话的即时测试）。

用法: python send_data.py <linear> <angular> <seconds>
前提: agent 已在 8888 上建立了 session 0x81，cmd_vel reader = 0x0006
"""
import os
import socket
import struct
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from xrce.cdr import twist_cdr
from xrce.frame import FLAG_ENDIANNESS, STREAM_BUILTIN_BEST_EFFORT, Message, Submessage, SUB_DATA

CLIENT_IP = "10.251.213.55"
PORT = 8888
SESSION = 0x81
READER = (0x00, 0x06)


def main():
    v = float(sys.argv[1]) if len(sys.argv) > 1 else 0.0
    w = float(sys.argv[2]) if len(sys.argv) > 2 else 0.0
    dur = float(sys.argv[3]) if len(sys.argv) > 3 else 0.3

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("0.0.0.0", PORT))
    seq = 0
    end = time.monotonic() + dur
    while time.monotonic() < end:
        payload = b"\x01\x00" + bytes(READER) + twist_cdr(v, w)
        msg = Message(SESSION, STREAM_BUILTIN_BEST_EFFORT, seq,
                      [Submessage(SUB_DATA, payload, FLAG_ENDIANNESS)])
        sock.sendto(msg.encode(), (CLIENT_IP, PORT))
        seq = (seq + 1) & 0xFFFF
        time.sleep(0.05)
    for _ in range(3):
        payload = b"\x01\x00" + bytes(READER) + twist_cdr(0.0, 0.0)
        msg = Message(SESSION, STREAM_BUILTIN_BEST_EFFORT, seq,
                      [Submessage(SUB_DATA, payload, FLAG_ENDIANNESS)])
        sock.sendto(msg.encode(), (CLIENT_IP, PORT))
        seq = (seq + 1) & 0xFFFF
        time.sleep(0.05)
    print(f"sent v={v} w={w} for {dur}s ({seq} packets)")


if __name__ == "__main__":
    main()
