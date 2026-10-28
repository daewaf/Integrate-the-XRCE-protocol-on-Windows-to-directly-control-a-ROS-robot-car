"""DDS-XRCE 1.0 消息帧与子消息编解码。

依据 OMG DDS-XRCE 1.0:
  - 8.3.2 Message Header
  - 8.3.4 Submessage Header
  - Table 10 SubmessageId values
"""
from __future__ import annotations

import struct
from dataclasses import dataclass, field

# Table 10 —— SubmessageId
SUB_CREATE_CLIENT = 0
SUB_CREATE = 1
SUB_GET_INFO = 2
SUB_DELETE = 3
SUB_STATUS_AGENT = 4
SUB_STATUS = 5
SUB_INFO = 6
SUB_WRITE_DATA = 7
SUB_READ_DATA = 8
SUB_DATA = 9
SUB_ACKNACK = 10
SUB_HEARTBEAT = 11
SUB_RESET = 12
SUB_FRAGMENT = 13
SUB_TIMESTAMP = 14
SUB_TIMESTAMP_REPLY = 15

SUB_NAMES = {
    SUB_CREATE_CLIENT: "CREATE_CLIENT",
    SUB_CREATE: "CREATE",
    SUB_GET_INFO: "GET_INFO",
    SUB_DELETE: "DELETE",
    SUB_STATUS_AGENT: "STATUS_AGENT",
    SUB_STATUS: "STATUS",
    SUB_INFO: "INFO",
    SUB_WRITE_DATA: "WRITE_DATA",
    SUB_READ_DATA: "READ_DATA",
    SUB_DATA: "DATA",
    SUB_ACKNACK: "ACKNACK",
    SUB_HEARTBEAT: "HEARTBEAT",
    SUB_RESET: "RESET",
    SUB_FRAGMENT: "FRAGMENT",
    SUB_TIMESTAMP: "TIMESTAMP",
    SUB_TIMESTAMP_REPLY: "TIMESTAMP_REPLY",
}

# Submessage flags (8.3.4.2 / 8.3.5.2.1)
FLAG_ENDIANNESS = 0x01  # 1 = little endian
FLAG_REUSE = 0x02
FLAG_REPLACE = 0x04

# Stream ids (8.3.2.2)
STREAM_NONE = 0x00
STREAM_BUILTIN_BEST_EFFORT = 0x01
STREAM_BUILTIN_RELIABLE = 0x80

# Session ids (8.3.2.1)
SESSION_NONE_WITH_CLIENT_KEY = 0x00
SESSION_NONE_WITHOUT_CLIENT_KEY = 0x80


def _pad4(buf: bytearray) -> None:
    while len(buf) % 4:
        buf.append(0)


@dataclass
class Submessage:
    id: int
    payload: bytes = b""
    flags: int = FLAG_ENDIANNESS

    def encode(self) -> bytes:
        """子消息头 4 字节 + payload；submessageLength 恒为小端。"""
        return struct.pack("<BBH", self.id, self.flags, len(self.payload)) + self.payload

    @classmethod
    def decode(cls, data: bytes, offset: int = 0) -> tuple["Submessage", int]:
        if len(data) < offset + 4:
            raise ValueError("submessage header truncated")
        sid, flags, length = struct.unpack_from("<BBH", data, offset)
        start = offset + 4
        end = start + length
        if end > len(data):
            raise ValueError(
                f"submessage {SUB_NAMES.get(sid, sid)} length {length} exceeds buffer"
            )
        return cls(id=sid, payload=bytes(data[start:end]), flags=flags), end


@dataclass
class Message:
    """一个 XRCE 消息 = 头部 + 一个或多个子消息。"""

    session_id: int
    stream_id: int
    sequence_nr: int
    submessages: list[Submessage] = field(default_factory=list)
    client_key: int | None = None

    def encode(self) -> bytes:
        buf = bytearray(struct.pack("<BBH", self.session_id, self.stream_id, self.sequence_nr))
        # sessionId <= 127 时必须携带 clientKey（8.3.2.1）
        if self.session_id <= 0x7F:
            if self.client_key is None:
                raise ValueError("session_id <= 127 requires client_key")
            buf += struct.pack("<I", self.client_key)
        for i, sm in enumerate(self.submessages):
            raw = bytearray(sm.encode())
            if i < len(self.submessages) - 1:
                _pad4(raw)  # 子消息起点需 4 字节对齐
            buf += raw
        return bytes(buf)

    @classmethod
    def decode(cls, data: bytes) -> "Message":
        if len(data) < 4:
            raise ValueError("message header truncated")
        session_id, stream_id, sequence_nr = struct.unpack_from("<BBH", data, 0)
        offset = 4
        client_key = None
        if session_id <= 0x7F:
            if len(data) < offset + 4:
                raise ValueError("client_key truncated")
            (client_key,) = struct.unpack_from("<I", data, offset)
            offset += 4

        submessages: list[Submessage] = []
        while offset < len(data):
            sm, end = Submessage.decode(data, offset)
            submessages.append(sm)
            offset = end
            while offset % 4 and offset < len(data):
                offset += 1
        return cls(
            session_id=session_id,
            stream_id=stream_id,
            sequence_nr=sequence_nr,
            submessages=submessages,
            client_key=client_key,
        )

    def __repr__(self) -> str:
        names = [SUB_NAMES.get(s.id, str(s.id)) for s in self.submessages]
        return (
            f"Message(session=0x{self.session_id:02X}, stream=0x{self.stream_id:02X}, "
            f"seq={self.sequence_nr}, client_key={self.client_key}, subs={names})"
        )
