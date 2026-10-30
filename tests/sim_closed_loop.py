"""模拟小车：接收 Twist、积分 odom 并回传，用于验证 forward/turn 闭环。"""
import math
import socket
import struct
import sys
import threading
import time

AGENT = ("127.0.0.1", 8888)
CONTROL = ("127.0.0.1", 8898)


def encode(session, stream, seq, subs):
    buf = bytearray([session, stream]) + struct.pack("<H", seq)
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


def pad(buf, n):
    while len(buf) % n:
        buf.append(0)


def cdr_odom(x, y, yaw):
    b = bytearray()
    b += struct.pack("<iI", int(time.time()), 0)
    b += struct.pack("<I", 5) + b"odom\x00"
    pad(b, 4)
    b += struct.pack("<I", 15) + b"base_footprint\x00"
    pad(b, 8)
    b += struct.pack("<ddd", x, y, 0.0)
    b += struct.pack("<dddd", 0.0, 0.0, math.sin(yaw / 2), math.cos(yaw / 2))
    return bytes(b)


def create_entity(seq, object_id, kind, topic_id):
    p = bytearray([0, seq]) + bytes(object_id) + bytes([kind, 0x03, 0, 0])
    p += struct.pack("<I", 0x8000000F)
    p += bytes(topic_id) + bytes([1, 0, 2, 0, 1])
    return encode(0x81, 0x80, seq, [(0x01, 0x07, bytes(p))])


def create_topic(seq, object_id, name):
    p = bytearray([0, seq]) + bytes(object_id) + bytes([0x02, 0x03, 0, 0])
    p += struct.pack("<I", 0x8000000C)
    p += struct.pack("<I", len(name) + 1) + name.encode() + b"\x00"
    return encode(0x81, 0x80, seq, [(0x01, 0x07, bytes(p))])


def control(cmd):
    s = socket.create_connection(CONTROL, timeout=15)
    s.sendall((cmd + "\n").encode())
    resp = b""
    while not resp.endswith(b"\n"):
        chunk = s.recv(512)
        if not chunk:
            break
        resp += chunk
    s.close()
    return resp.decode(errors="replace").strip()


def main():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("127.0.0.1", 0))
    sock.settimeout(0.05)

    now = time.time_ns()
    hello = bytearray(b"XRCE") + bytes([1, 0, 1, 0x0F])
    hello += struct.pack("<iI", now // 1_000_000_000, now % 1_000_000_000)
    hello += struct.pack("<I", 0x55667788) + bytes([0x81, 0])
    sock.sendto(encode(0x80, 0, 0, [(0x00, 0x01, bytes(hello))]), AGENT)
    sock.recvfrom(4096)

    sock.sendto(create_topic(0, (0, 0x22), "rt/cmd_vel"), AGENT)
    sock.sendto(create_entity(1, (0, 6), 0x06, (0, 0x22)), AGENT)
    sock.sendto(create_topic(2, (0, 0x02), "rt/odom"), AGENT)
    sock.sendto(create_entity(3, (0, 5), 0x05, (0, 0x02)), AGENT)
    time.sleep(0.3)

    state = {"x": 0.0, "y": 0.0, "yaw": 0.0, "v": 0.0, "w": 0.0}
    stop = threading.Event()

    def sim():
        last = time.monotonic()
        last_odom = 0.0
        seq = 0
        while not stop.is_set():
            now_t = time.monotonic()
            try:
                data, _ = sock.recvfrom(4096)
                for sid, _, payload in decode(data)[3]:
                    if sid == 0x09 and len(payload) >= 52:
                        state["v"] = struct.unpack_from("<d", payload, 4)[0]
                        state["w"] = struct.unpack_from("<d", payload, 4 + 40)[0]
            except socket.timeout:
                pass

            dt = now_t - last
            last = now_t
            state["yaw"] += state["w"] * dt
            state["x"] += state["v"] * math.cos(state["yaw"]) * dt
            state["y"] += state["v"] * math.sin(state["yaw"]) * dt

            if now_t - last_odom > 0.05:
                last_odom = now_t
                body = struct.pack("<H", seq) + bytes((0, 5)) + cdr_odom(state["x"], state["y"], state["yaw"])
                sock.sendto(encode(0x81, 0x01, seq, [(0x07, 0x01, body)]), AGENT)
                seq = (seq + 1) & 0xFFFF

    thread = threading.Thread(target=sim, daemon=True)
    thread.start()
    time.sleep(1.0)

    print("status:", control("status"))
    print("forward:", control("forward 0.10 0.05"), f"pose=({state['x']:.3f},{state['y']:.3f})")
    print("turn:", control("turn 30 0.3"), f"yaw={math.degrees(state['yaw']):.1f}")
    print("back:", control("forward -0.05 0.05"), f"pose=({state['x']:.3f},{state['y']:.3f})")
    print("stop:", control("stop"))

    stop.set()
    thread.join(timeout=1)
    return 0


if __name__ == "__main__":
    sys.exit(main())
