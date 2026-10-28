"""自包含的合成 XRCE 客户端：验证 C# agent 的 CREATE / READ_DATA / DATA 路径。

用法: python tests/synthetic_client.py
前提: C# agent 已在本机 127.0.0.1:8888 运行，控制口 8898 可用。
"""
import socket
import struct
import sys
import time

AGENT = ("127.0.0.1", 8888)
CONTROL = ("127.0.0.1", 8898)


def encode(session, stream, seq, subs):
    """subs: [(id, flags, payload), ...]"""
    buf = bytearray([session, stream])
    buf += struct.pack("<H", seq)
    if session <= 0x7F:
        buf += struct.pack("<I", 0)
    for i, (sid, flags, payload) in enumerate(subs):
        buf += bytes([sid, flags]) + struct.pack("<H", len(payload)) + payload
        if i < len(subs) - 1:
            while len(buf) % 4:
                buf.append(0)
    return bytes(buf)


def decode(data):
    session, stream, seq = struct.unpack_from("<BBH", data, 0)
    off = 4 + (4 if session <= 0x7F else 0)
    subs = []
    while off + 4 <= len(data):
        sid, flags, length = struct.unpack_from("<BBH", data, off)
        start = off + 4
        subs.append((sid, flags, data[start:start + length]))
        off = start + length
        while off % 4 and off < len(data):
            off += 1
    return session, stream, seq, subs


def create_topic(seq, object_id, name):
    payload = bytearray([0, seq]) + bytes(object_id)
    payload += bytes([0x02, 0x03, 0x00, 0x00])
    payload += struct.pack("<I", 0x8000000C)
    payload += struct.pack("<I", len(name) + 1) + name.encode() + b"\x00"
    return encode(0x81, 0x80, seq, [(0x01, 0x07, bytes(payload))])


def create_reader(seq, object_id, topic_id):
    payload = bytearray([0, seq]) + bytes(object_id)
    payload += bytes([0x06, 0x03, 0x00, 0x00])
    payload += struct.pack("<I", 0x8000000F)
    payload += bytes(topic_id) + bytes([0x01, 0x00, 0x02, 0x00, 0x01])
    return encode(0x81, 0x80, seq, [(0x01, 0x07, bytes(payload))])


def main():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("127.0.0.1", 0))
    sock.settimeout(3)

    now = time.time_ns()
    payload = bytearray(b"XRCE")
    payload += bytes([0x01, 0x00, 0x01, 0x0F])
    payload += struct.pack("<iI", now // 1_000_000_000, now % 1_000_000_000)
    payload += struct.pack("<I", 0x11223344) + bytes([0x81, 0x00])
    sock.sendto(encode(0x80, 0, 0, [(0x00, 0x01, bytes(payload))]), AGENT)
    data, _ = sock.recvfrom(4096)
    print("STATUS_AGENT:", len(data), "bytes")

    sock.sendto(create_topic(0, (0x00, 0x22), "rt/cmd_vel"), AGENT)
    sock.sendto(create_reader(1, (0x00, 0x06), (0x00, 0x22)), AGENT)
    time.sleep(0.2)
    sock.sendto(encode(0x81, 0x01, 0, [(0x08, 0x01, bytes([0, 1, 0, 6]))]), AGENT)
    time.sleep(0.2)

    # 清空命令之前积压的零值 DATA
    sock.setblocking(False)
    try:
        while True:
            sock.recvfrom(4096)
    except BlockingIOError:
        pass
    sock.setblocking(True)

    tcp = socket.create_connection(CONTROL, timeout=3)
    tcp.sendall(b"0.05 0 0.6\n")
    print("control:", tcp.recv(128).decode().strip())
    tcp.close()

    seen = 0
    values = []
    end = time.time() + 1.2
    sock.settimeout(0.2)
    while time.time() < end:
        try:
            data, _ = sock.recvfrom(4096)
        except socket.timeout:
            continue
        for sid, _, payload in decode(data)[3]:
            if sid != 0x09 or len(payload) < 52:
                continue
            seen += 1
            (v,) = struct.unpack_from("<d", payload, 4 + 0)
            (w,) = struct.unpack_from("<d", payload, 4 + 40)
            values.append(v)
            print(f"DATA obj=0x{payload[2]:02X}{payload[3]:02X} v={v:.3f} w={w:.3f}")

    print("DATA count:", seen, "max v:", max(values) if values else None)
    return 0 if values and max(values) > 0.04 else 1


if __name__ == "__main__":
    sys.exit(main())
