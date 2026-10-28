"""最小 XCDR（little endian）读写器。

只实现 FishBot 需要的部分：整数、float64、字符串、原始字节。
对齐规则遵循 DDS-XTypes 的 XCDR：基本类型按自身大小对齐，
字符串为 uint32 长度（含结尾 NUL）+ 字节。
"""
from __future__ import annotations

import struct
import math


class CDRWriter:
    def __init__(self) -> None:
        self.buf = bytearray()

    def align(self, n: int) -> "CDRWriter":
        while len(self.buf) % n:
            self.buf.append(0)
        return self

    def u8(self, v: int) -> "CDRWriter":
        self.buf += struct.pack("<B", v)
        return self

    def u16(self, v: int) -> "CDRWriter":
        self.align(2)
        self.buf += struct.pack("<H", v)
        return self

    def i32(self, v: int) -> "CDRWriter":
        self.align(4)
        self.buf += struct.pack("<i", v)
        return self

    def u32(self, v: int) -> "CDRWriter":
        self.align(4)
        self.buf += struct.pack("<I", v)
        return self

    def f64(self, v: float) -> "CDRWriter":
        self.align(8)
        self.buf += struct.pack("<d", v)
        return self

    def string(self, s: str) -> "CDRWriter":
        raw = s.encode("utf-8") + b"\x00"
        self.u32(len(raw))
        self.buf += raw
        return self

    def raw(self, b: bytes) -> "CDRWriter":
        self.buf += b
        return self

    def dheader(self, payload_len: int) -> "CDRWriter":
        """APPENDABLE 类型的 DHEADER：最高位=1，低 31 位为长度。"""
        self.u32(0x80000000 | (payload_len & 0x7FFFFFFF))
        return self

    def bytes(self) -> bytes:
        return bytes(self.buf)

    def __len__(self) -> int:
        return len(self.buf)


class CDRReader:
    def __init__(self, data: bytes, offset: int = 0) -> None:
        self.data = data
        self.offset = offset

    def align(self, n: int) -> "CDRReader":
        while self.offset % n:
            self.offset += 1
        return self

    def _take(self, n: int) -> bytes:
        end = self.offset + n
        if end > len(self.data):
            raise ValueError("CDR buffer underflow")
        chunk = self.data[self.offset:end]
        self.offset = end
        return chunk

    def u8(self) -> int:
        return struct.unpack("<B", self._take(1))[0]

    def u16(self) -> int:
        self.align(2)
        return struct.unpack("<H", self._take(2))[0]

    def i32(self) -> int:
        self.align(4)
        return struct.unpack("<i", self._take(4))[0]

    def u32(self) -> int:
        self.align(4)
        return struct.unpack("<I", self._take(4))[0]

    def f64(self) -> float:
        self.align(8)
        return struct.unpack("<d", self._take(8))[0]

    def string(self) -> str:
        n = self.u32()
        raw = self._take(n)
        return raw.rstrip(b"\x00").decode("utf-8", errors="replace")


def twist_cdr(linear_x: float = 0.0, angular_z: float = 0.0) -> bytes:
    """geometry_msgs/msg/Twist 的 CDR 序列化（6 个 float64，共 48 字节）。"""
    w = CDRWriter()
    for v in (linear_x, 0.0, 0.0, 0.0, 0.0, angular_z):
        w.f64(v)
    return w.bytes()


def odom_pose_cdr(data: bytes) -> tuple[float, float, float]:
    """解析 nav_msgs/msg/Odometry 的 x, y, yaw。"""
    r = CDRReader(data)
    r.i32()          # stamp.sec
    r.u32()          # stamp.nanosec
    r.string()       # header.frame_id
    r.string()       # child_frame_id
    x = r.f64()
    y = r.f64()
    r.f64()          # z
    qx = r.f64()
    qy = r.f64()
    qz = r.f64()
    qw = r.f64()
    yaw = math.atan2(2 * (qw * qz + qx * qy), 1 - 2 * (qy * qy + qz * qz))
    return x, y, math.degrees(yaw)
