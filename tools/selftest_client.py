"""本地自测：向运行中的 agent 发一个 CREATE_CLIENT，打印它的应答。"""
import socket
import struct
import sys
import time
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from xrce.agent import hexdump
from xrce.frame import (
    FLAG_ENDIANNESS,
    SESSION_NONE_WITHOUT_CLIENT_KEY,
    STREAM_NONE,
    Message,
    Submessage,
    SUB_CREATE_CLIENT,
)


def main() -> int:
    host = sys.argv[1] if len(sys.argv) > 1 else "127.0.0.1"
    port = int(sys.argv[2]) if len(sys.argv) > 2 else 8888

    now_ns = time.time_ns()
    payload = bytearray()
    payload += b"XRCE"
    payload += bytes([0x01, 0x00])              # version 1.0
    payload += bytes([0x01, 0x0F])              # vendor
    payload += struct.pack("<iI", now_ns // 1_000_000_000, now_ns % 1_000_000_000)
    payload += struct.pack("<I", 0x11223344)    # client_key
    payload += bytes([0x81])                    # requested session_id
    payload += b"\x00"                          # properties absent

    msg = Message(
        session_id=SESSION_NONE_WITHOUT_CLIENT_KEY,
        stream_id=STREAM_NONE,
        sequence_nr=0,
        submessages=[Submessage(SUB_CREATE_CLIENT, bytes(payload), FLAG_ENDIANNESS)],
    )
    raw = msg.encode()
    print("TX", len(raw), "bytes")
    print(hexdump(raw))

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(3.0)
    sock.sendto(raw, (host, port))
    try:
        data, addr = sock.recvfrom(4096)
    except socket.timeout:
        print("未收到应答")
        return 1
    print(f"RX from {addr}: {len(data)} bytes")
    print(hexdump(data))
    return 0


if __name__ == "__main__":
    sys.exit(main())
