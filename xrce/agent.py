"""Windows 纯 Python 的 DDS-XRCE 最小 agent（研究/验证版）。

目标：不依赖 WSL、不依赖 ROS2，直接和 FishBot 主控板的 micro-ROS 客户端
建立 XRCE 会话，向其 DataReader 下发 geometry_msgs/Twist，并解析其
DataWriter 上报的数据。

当前实现会：
  - 监听 UDP 8888，解析 MessageHeader / Submessage
  - 对 CREATE_CLIENT 回复 STATUS_AGENT
  - 对 CREATE 回复 STATUS(OK)
  - 记录所有未知/待确认的字节（用于和真实板子联调）
  - 把收到的 WRITE_DATA 以十六进制落盘

用法:
  python -m xrce.agent --port 8888 --hexlog logs
"""
from __future__ import annotations

import argparse
import datetime as dt
import os
import socket
import socketserver
import struct
import sys
import threading
import time
from dataclasses import dataclass, field

from .frame import (
    FLAG_ENDIANNESS,
    Message,
    STREAM_BUILTIN_BEST_EFFORT,
    STREAM_BUILTIN_RELIABLE,
    STREAM_NONE,
    SUB_CREATE,
    SUB_CREATE_CLIENT,
    SUB_DATA,
    SUB_DELETE,
    SUB_GET_INFO,
    SUB_INFO,
    SUB_HEARTBEAT,
    SUB_ACKNACK,
    SUB_TIMESTAMP,
    SUB_TIMESTAMP_REPLY,
    SUB_READ_DATA,
    SUB_STATUS,
    SUB_STATUS_AGENT,
    SUB_WRITE_DATA,
    Submessage,
    SUB_NAMES,
)

OBJK_PARTICIPANT = 0x01
OBJK_TOPIC = 0x02
OBJK_PUBLISHER = 0x03
OBJK_SUBSCRIBER = 0x04
OBJK_DATAWRITER = 0x05
OBJK_DATAREADER = 0x06

STATUS_OK = 0x00
SERVICE_OBJECT = (0x00, 0x08)   # FishBot 的 fishbot_config 服务端点，不是 cmd_vel

# 抓包确认的 FishBot 固件对象表（接管旧会话时用于自愈）
DEFAULT_FISHBOT_OBJECTS = {
    (0x00, 0x01): (OBJK_PARTICIPANT, None),
    (0x00, 0x02): (OBJK_TOPIC, "odom"),
    (0x00, 0x03): (OBJK_PUBLISHER, None),
    (0x00, 0x05): (OBJK_DATAWRITER, "odom"),
    (0x00, 0x12): (OBJK_TOPIC, "imu"),
    (0x00, 0x13): (OBJK_PUBLISHER, None),
    (0x00, 0x15): (OBJK_DATAWRITER, "imu"),
    (0x00, 0x22): (OBJK_TOPIC, "cmd_vel"),
    (0x00, 0x04): (OBJK_SUBSCRIBER, None),
    (0x00, 0x06): (OBJK_DATAREADER, "cmd_vel"),
    (0x00, 0x08): (0x08, None),
}

# 官方 agent 对 AGENT GET_INFO 的固定应答尾部（抓包确认，22 字节）
INFO_TAIL = bytes.fromhex(
    "01 0D 58 52 43 45 01 00 01 0F 00 01 0D 00 01 00 00 00 00 00 00 00"
)

# Windows 控制台/重定向文件统一用 UTF-8，避免中文乱码
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass


def hexdump(data: bytes, prefix: str = "") -> str:
    lines = []
    for i in range(0, len(data), 16):
        chunk = data[i : i + 16]
        hx = " ".join(f"{b:02X}" for b in chunk)
        txt = "".join(chr(b) if 32 <= b < 127 else "." for b in chunk)
        lines.append(f"{prefix}{i:04X}  {hx:<47}  {txt}")
    return "\n".join(lines)


@dataclass
class XrceObject:
    object_id: tuple[int, int]
    kind: int
    topic: str | None = None
    type_name: str | None = None


@dataclass
class ClientSession:
    addr: tuple[str, int]
    client_key: int
    session_id: int
    seq_out: dict[int, int] = field(default_factory=dict)
    objects: dict[tuple[int, int], XrceObject] = field(default_factory=dict)
    last_data: bytes | None = None

    def next_seq(self, stream: int) -> int:
        n = self.seq_out.get(stream, 0)
        self.seq_out[stream] = (n + 1) & 0xFFFF
        return n

    def find_reader(self, needle: str) -> tuple[int, int] | None:
        for obj in self.objects.values():
            if obj.kind == OBJK_DATAREADER and obj.topic and needle in obj.topic:
                return obj.object_id
        return None

    def find_any_reader(self) -> tuple[int, int] | None:
        for obj in self.objects.values():
            if obj.kind == OBJK_DATAREADER and obj.object_id != SERVICE_OBJECT:
                return obj.object_id
        return None


class XrceAgent:
    def __init__(self, host: str = "0.0.0.0", port: int = 8888,
                 hexlog_dir: str | None = None, verbose: bool = True,
                 info_delay: float = 0.005) -> None:
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind((host, port))
        self.sock.settimeout(0.2)
        self.sessions: dict[tuple[str, int], ClientSession] = {}
        self.verbose = verbose
        self.hexlog_dir = hexlog_dir
        self.running = True
        self.dds_log: list[str] = []
        self.current_twist: tuple[float, float] = (0.0, 0.0)
        self._data_request_id = 0
        self.info_delay = info_delay
        self.reply_info = True
        self.reply_read = False
        if hexlog_dir:
            os.makedirs(hexlog_dir, exist_ok=True)
        self.control_server = None

    # ---------------- 收发 ----------------
    def send(self, session: ClientSession, stream_id: int, subs: list[Submessage]) -> None:
        # STREAMID_NONE(0) 不参与排序，官方 agent 始终用 seq 0
        seq = 0 if stream_id == STREAM_NONE else session.next_seq(stream_id)
        msg = Message(
            session_id=session.session_id,
            stream_id=stream_id,
            sequence_nr=seq,
            submessages=subs,
            client_key=session.client_key if session.session_id <= 0x7F else None,
        )
        raw = msg.encode()
        self.sock.sendto(raw, session.addr)
        self.log(f"TX {stream_id=} {len(raw)}B\n{hexdump(raw, '    ')}")

    def log(self, text: str) -> None:
        if self.verbose:
            print(f"[{dt.datetime.now().strftime('%H:%M:%S')}] {text}", flush=True)

    # ---------------- 处理 ----------------
    def serve(self) -> None:
        self.log(f"agent listening on udp {self.sock.getsockname()}")
        while self.running:
            try:
                data, addr = self.sock.recvfrom(65535)
            except socket.timeout:
                continue
            except KeyboardInterrupt:
                break
            try:
                self.handle(addr, data)
            except Exception as exc:  # noqa: BLE001
                self.log(f"处理失败 {addr}: {exc}")
                self.dump_hex("error", data)

    def handle(self, addr: tuple[str, int], data: bytes) -> None:
        msg = Message.decode(data)
        names = ",".join(SUB_NAMES.get(s.id, str(s.id)) for s in msg.submessages)
        self.log(f"RX {addr[0]}:{addr[1]} session=0x{msg.session_id:02X} "
                 f"stream=0x{msg.stream_id:02X} seq={msg.sequence_nr} subs=[{names}]")

        if msg.session_id >= 0x80 and msg.session_id != 0x80:
            # sessionId >= 128 时 session 由源地址界定
            session = self.sessions.get(addr)
        else:
            session = self.sessions.get(addr)

        # 客户端在 agent 重启后会沿用旧 session，不再发送 CREATE_CLIENT。
        # 这里自动接管，保证 WASD/指令在重启后仍可用。
        if session is None and msg.session_id >= 0x81:
            session = ClientSession(addr=addr, client_key=0, session_id=msg.session_id)
            for oid, (kind, topic) in DEFAULT_FISHBOT_OBJECTS.items():
                session.objects[oid] = XrceObject(oid, kind, topic)
            self.sessions[addr] = session
            self.log(f"  自动接管已有会话 session=0x{msg.session_id:02X}")

        for sm in msg.submessages:
            self.log(f"  payload {len(sm.payload)}B\n{hexdump(sm.payload, '    ')}")
            self.dump_hex(f"rx_{sm.id:02X}", sm.payload)
            if sm.id == SUB_CREATE_CLIENT:
                self.on_create_client(addr, msg, sm)
                session = self.sessions.get(addr)
            elif sm.id == SUB_CREATE:
                if session is None:
                    self.log("  ! CREATE before CREATE_CLIENT，忽略")
                    continue
                self.on_create(session, sm, msg.stream_id)
            elif sm.id == SUB_WRITE_DATA:
                if session is None:
                    continue
                self.on_write_data(session, sm)
            elif sm.id == SUB_READ_DATA:
                self.log("  READ_DATA（客户端轮询数据）")
                if session is not None:
                    self.on_read_data(session, sm)
            elif sm.id == SUB_GET_INFO:
                self.on_get_info(addr, msg, sm)
            elif sm.id == SUB_HEARTBEAT:
                # 客户端心跳：在 stream 0 上回 ACKNACK
                if session is not None:
                    self.send_acknack(session, msg.sequence_nr)
            elif sm.id == SUB_TIMESTAMP:
                if session is not None:
                    self.on_timestamp(session, sm)
            elif sm.id == SUB_DELETE:
                if session is not None:
                    self.on_delete(session, sm, msg.stream_id)

        # 可靠流上的请求需要 ACK，否则客户端会重传
        if msg.stream_id >= 0x80 and msg.submessages:
            sess = self.sessions.get(addr)
            if sess is not None and not any(s.id == SUB_ACKNACK for s in msg.submessages):
                self.send_acknack(sess, msg.sequence_nr)

    def on_create_client(self, addr: tuple[str, int], msg: Message, sm: Submessage) -> None:
        payload = sm.payload
        self.log(f"  CREATE_CLIENT payload {len(payload)}B\n{hexdump(payload, '    ')}")
        self.dump_hex("create_client", payload)

        # 客户端请求的 session_id：规范在 CLIENT_Representation 末尾；
        # 这里做启发式解析，真实布局以抓包为准。
        client_key = None
        requested = 0x81
        if payload[:4] == b"XRCE":
            # 两种版本的 CLIENT_Representation：
            #   有 client_timestamp 时：cookie4+ver2+vendor2+ts8+key4+sid1+props1 = 22
            #   无 client_timestamp 时：cookie4+ver2+vendor2+key4+sid1+props1     = 14
            key_off = 16 if len(payload) >= 22 else 8
            if len(payload) >= key_off + 5:
                client_key = struct.unpack_from("<I", payload, key_off)[0]
                requested = payload[key_off + 4]
        if client_key is None and msg.client_key is not None:
            client_key = msg.client_key

        session_id = requested if requested >= 0x80 else (requested or 0x81)
        session = ClientSession(addr=addr, client_key=client_key or 0, session_id=session_id)
        self.sessions[addr] = session
        self.log(f"  新会话: client_key=0x{session.client_key:08X} session_id=0x{session_id:02X}")

        # 抓包确认的 STATUS_AGENT payload（11 B）：
        #   00 00 + "XRCE" + 01 00 + 01 0F + 00
        agent_rep = bytes.fromhex("00 00") + b"XRCE" + bytes([0x01, 0x00, 0x01, 0x0F, 0x00])
        self.send(session, STREAM_NONE,
                  [Submessage(SUB_STATUS_AGENT, bytes(agent_rep), FLAG_ENDIANNESS)])

    def on_get_info(self, addr, msg: Message, sm: Submessage) -> None:
        """GET_INFO(AGENT) -> INFO，使用抓包得到的官方常量尾部。"""
        if not self.reply_info:
            self.log("  GET_INFO（按配置不回复）")
            return
        p = sm.payload
        if len(p) < 4:
            return
        request_id = p[0:2]
        object_id = p[2:4]
        # 抓包对比：预会话(session 0x80) 的 BaseObjectReply 为 00 00；
        # 会话内(0x81) 的 implementation_status 为 01，否则客户端会重建会话。
        impl = b"\x00\x00" if msg.session_id == 0x80 else b"\x00\x01"
        payload = request_id + object_id + impl + INFO_TAIL
        # GET_INFO 发生在会话建立前（session 0x80），必须原样用 0x80 回应，
        # 不能复用旧的 0x81 会话（否则客户端会忽略该回复）。
        target = ClientSession(addr=addr, client_key=0, session_id=msg.session_id)
        # micro-ROS 客户端在发出 GET_INFO 后才进入接收等待；单次回复存在竞态，
        # 在短窗口内重发几次（客户端按 request_id 去重，重复无害）。
        # 与官方 agent 的时序对齐：短延时后单次回复
        time.sleep(self.info_delay)
        self.send(target, STREAM_NONE,
                  [Submessage(SUB_INFO, payload, FLAG_ENDIANNESS)])

    def on_timestamp(self, session: ClientSession, sm: Submessage) -> None:
        """回 TIMESTAMP_REPLY：agent 发送时间 + agent 接收时间 + 客户端时间。"""
        now_ns = time.time_ns()
        stamp = struct.pack("<iI", now_ns // 1_000_000_000, now_ns % 1_000_000_000)
        payload = stamp + stamp + sm.payload
        self.send(session, STREAM_NONE,
                  [Submessage(SUB_TIMESTAMP_REPLY, payload, FLAG_ENDIANNESS)])

    def send_acknack(self, session: ClientSession, seq: int) -> None:
        payload = struct.pack("<H", (seq + 1) & 0xFFFF) + b"\x00\x00\x80"
        self.send(session, STREAM_NONE,
                  [Submessage(SUB_ACKNACK, payload, FLAG_ENDIANNESS)])

    def on_read_data(self, session: ClientSession, sm: Submessage) -> None:
        """客户端轮询 cmd_vel 的 DataReader 时，回送当前指令。"""
        p = sm.payload
        if len(p) < 4:
            return
        object_id = (p[2], p[3])
        obj = session.objects.get(object_id)
        if obj is None and object_id != SERVICE_OBJECT:
            # 自愈：从 READ_DATA 学习 DataReader（FishBot 只有一个 cmd_vel reader）
            obj = XrceObject(object_id, OBJK_DATAREADER)
            session.objects[object_id] = obj
            self.log(f"  学习到 DataReader 0x{p[2]:02X}0x{p[3]:02X}")
        if not self.reply_read:
            return
        if obj is None or obj.kind != OBJK_DATAREADER:
            return
        if not obj.topic or "cmd_vel" not in obj.topic:
            return
        from .cdr import twist_cdr

        v, w = getattr(self, "current_twist", (0.0, 0.0))
        payload = p[0:2] + bytes(object_id) + twist_cdr(v, w)
        self.send(session, STREAM_BUILTIN_BEST_EFFORT,
                  [Submessage(SUB_DATA, payload, FLAG_ENDIANNESS)])

    def on_delete(self, session: ClientSession, sm: Submessage, stream_id: int) -> None:
        """DELETE 与 CREATE 一样，必须回 STATUS，否则客户端会超时重建会话。"""
        p = sm.payload
        if len(p) < 4:
            return
        request_id = (p[0], p[1])
        object_id = (p[2], p[3])
        status = bytes(request_id) + bytes(object_id) + bytes([STATUS_OK, 0x00])
        self.log(f"  DELETE request={request_id} object=0x{p[2]:02X}0x{p[3]:02X} -> STATUS OK")
        self.send(session, stream_id, [Submessage(SUB_STATUS, status, FLAG_ENDIANNESS)])

    def on_create(self, session: ClientSession, sm: Submessage, stream_id: int) -> None:
        p = sm.payload
        if len(p) < 5:
            self.log("  CREATE 过短")
            return
        request_id = (p[0], p[1])
        object_id = (p[2], p[3])
        kind = p[4]
        topic = self.guess_topic(p)
        if kind in (OBJK_DATAREADER, OBJK_DATAWRITER):
            # DataReader/DataWriter 用 topic_id 引用话题；抓包确认引用位于偏移 12
            ref = (p[12], p[13]) if len(p) >= 14 else None
            if ref is not None and ref in session.objects:
                obj = session.objects[ref]
                if obj.kind == OBJK_TOPIC:
                    topic = obj.topic
            if topic is None:
                for oid, obj in session.objects.items():
                    if obj.kind == OBJK_TOPIC and bytes(oid) in p:
                        topic = obj.topic
                        break
        self.log(f"  CREATE request={request_id} object=0x{p[2]:02X}0x{p[3]:02X} "
                 f"kind=0x{kind:02X} topic={topic!r}")
        self.log(f"    payload {len(p)}B\n{hexdump(p, '      ')}")
        self.dump_hex(f"create_{kind:02X}", p)
        session.objects[object_id] = XrceObject(object_id, kind, topic)
        # STATUS: BaseObjectReply = request_id(2) + object_id(2) + status(1) + impl(1)
        status = bytes(request_id) + bytes(object_id) + bytes([STATUS_OK, 0x00])
        self.send(session, stream_id, [Submessage(SUB_STATUS, status, FLAG_ENDIANNESS)])
        # 主动发 HEARTBEAT，告知客户端可靠流上的可用序号
        seq = session.seq_out.get(STREAM_BUILTIN_RELIABLE, 1) - 1
        hb = struct.pack("<HHB", seq & 0xFFFF, seq & 0xFFFF, 0x80)
        self.send(session, STREAM_NONE, [Submessage(SUB_HEARTBEAT, hb, FLAG_ENDIANNESS)])

    def on_write_data(self, session: ClientSession, sm: Submessage) -> None:
        p = sm.payload
        if len(p) < 4:
            return
        request_id = (p[0], p[1])
        object_id = (p[2], p[3])
        data = bytes(p[4:])
        session.last_data = data
        obj = session.objects.get(object_id)
        if obj is None and b"odom" in data[:48]:
            obj = XrceObject(object_id, OBJK_DATAWRITER, "odom")
            session.objects[object_id] = obj
        self.log(f"  WRITE_DATA request={request_id} object=0x{p[2]:02X}0x{p[3]:02X} "
                 f"data={len(data)}B topic={obj.topic if obj else None}")
        if obj is not None and obj.topic and "odom" in obj.topic:
            try:
                from .cdr import odom_pose_cdr

                x, y, yaw = odom_pose_cdr(data)
                self.log(f"    odom x={x:+.3f} y={y:+.3f} yaw={yaw:+.1f}deg")
            except Exception as exc:  # noqa: BLE001
                self.log(f"    odom 解析失败: {exc}")
        self.dump_hex("write_data", p)

    @staticmethod
    def guess_topic(payload: bytes) -> str | None:
        for needle in (b"cmd_vel", b"odom", b"imu"):
            idx = payload.find(needle)
            if idx >= 0:
                return needle.decode()
        return None

    def dump_hex(self, tag: str, data: bytes) -> None:
        if not self.hexlog_dir:
            return
        ts = dt.datetime.now().strftime("%H%M%S_%f")
        path = os.path.join(self.hexlog_dir, f"{ts}_{tag}.bin")
        with open(path, "wb") as fh:
            fh.write(data)

    # ---------------- 主动下发 ----------------
    def send_twist(self, linear_x: float, angular_z: float) -> bool:
        from .cdr import twist_cdr

        sent = False
        payload = twist_cdr(linear_x, angular_z)
        for session in self.sessions.values():
            reader = session.find_reader("cmd_vel") or session.find_any_reader()
            if not reader:
                continue
            self._data_request_id = (self._data_request_id + 1) & 0xFFFF
            body = struct.pack("<H", self._data_request_id) + bytes(reader) + payload
            self.send(session, STREAM_BUILTIN_BEST_EFFORT,
                      [Submessage(SUB_DATA, body, FLAG_ENDIANNESS)])
            sent = True
        return sent

    def publish_twist_stream(self, v: float, w: float, duration: float, hz: float = 20.0) -> None:
        """持续下发 Twist，并在结束时归零。"""
        self.current_twist = (v, w)
        end = time.monotonic() + duration
        while time.monotonic() < end and self.running:
            self.send_twist(v, w)
            time.sleep(1.0 / hz)
        self.current_twist = (0.0, 0.0)
        for _ in range(3):
            self.send_twist(0.0, 0.0)
            time.sleep(0.05)

    # ---------------- 本地控制口 ----------------
    def start_control_server(self, host: str = "127.0.0.1", port: int = 8899) -> None:
        agent = self

        # 所有运动指令共用一个 setpoint，由单一线程以固定频率发布。
        # 每次按键只更新时间戳/速度，避免几十个线程同时发包导致轮子顿挫。
        class TwistController:
            def __init__(self, hz: float = 20.0):
                self.hz = hz
                self._lock = threading.Lock()
                self._target = (0.0, 0.0)
                self._deadline = 0.0
                self._thread = threading.Thread(target=self._run, daemon=True)
                self._thread.start()

            def set(self, v: float, w: float, duration: float):
                with self._lock:
                    self._target = (v, w)
                    self._deadline = time.monotonic() + max(duration, 0.05)

            def stop(self):
                with self._lock:
                    self._target = (0.0, 0.0)
                    self._deadline = 0.0

            def _run(self):
                period = 1.0 / self.hz
                while agent.running:
                    with self._lock:
                        expired = time.monotonic() > self._deadline
                        v, w = (0.0, 0.0) if expired else self._target
                    agent.send_twist(v, w)
                    time.sleep(period)

        self.controller = TwistController()
        controller = self.controller

        class Handler(socketserver.StreamRequestHandler):
            def handle(self):
                try:
                    # 一条 TCP 连接上可以连续发多条指令（WASD 遥控依赖这一点）
                    while True:
                        raw = self.rfile.readline()
                        if not raw:
                            return
                        line = raw.decode("utf-8", "replace").strip()
                        if not line:
                            continue
                        try:
                            parts = line.split()
                            v = float(parts[0])
                            w = float(parts[1]) if len(parts) > 1 else 0.0
                            d = float(parts[2]) if len(parts) > 2 else 0.5
                        except Exception:
                            self.wfile.write(b"ERR usage: <linear> <angular> <seconds>\n")
                            self.wfile.flush()
                            continue
                        if v == 0.0 and w == 0.0:
                            controller.stop()
                        else:
                            controller.set(v, w, d)
                        self.wfile.write(f"OK {v} {w} {d}\n".encode())
                        self.wfile.flush()
                except Exception as exc:  # noqa: BLE001
                    agent.log(f"control handler error: {exc!r}")

        class Server(socketserver.ThreadingTCPServer):
            allow_reuse_address = True

        srv = Server((host, port), Handler)
        srv.agent = self  # type: ignore[attr-defined]
        self.control_server = srv
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.log(f"control server listening on tcp {host}:{port}")

    def start_heartbeat(self, period: float = 2.0) -> None:
        """周期发送 HEARTBEAT，维持可靠流的会话活性。"""
        def loop():
            while self.running:
                time.sleep(period)
                for session in list(self.sessions.values()):
                    last = max(session.seq_out.get(STREAM_BUILTIN_RELIABLE, 1) - 1, 0)
                    hb = struct.pack("<HHB", last & 0xFFFF, last & 0xFFFF, 0x80)
                    try:
                        self.send(session, STREAM_NONE,
                                  [Submessage(SUB_HEARTBEAT, hb, FLAG_ENDIANNESS)])
                    except Exception:  # noqa: BLE001
                        pass

        threading.Thread(target=loop, daemon=True).start()


def session_stream(sm: Submessage) -> int:
    return STREAM_BUILTIN_BEST_EFFORT


def main() -> None:
    ap = argparse.ArgumentParser(description="纯 Python XRCE-DDS agent（Windows）")
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--port", type=int, default=8888)
    ap.add_argument("--hexlog", default=None, help="把收到的 payload 落盘到该目录")
    ap.add_argument("--control-port", type=int, default=8898,
                    help="本地 TCP 控制口（0 表示关闭）")
    ap.add_argument("--info-delay", type=float, default=0.005,
                    help="回复 GET_INFO 前的延时秒数（micro-ROS 客户端时序需要）")
    ap.add_argument("--no-info", action="store_true", help="不回复 GET_INFO（诊断用）")
    ap.add_argument("--reply-read", action="store_true",
                    help="回复 READ_DATA 轮询（默认关闭，与官方 agent 行为一致）")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()
    agent = XrceAgent(args.host, args.port, args.hexlog, not args.quiet,
                      info_delay=args.info_delay)
    agent.reply_info = not args.no_info
    agent.reply_read = args.reply_read
    agent.start_heartbeat()
    if args.control_port:
        agent.start_control_server(port=args.control_port)
    try:
        agent.serve()
    except KeyboardInterrupt:
        pass
    finally:
        agent.running = False


if __name__ == "__main__":
    main()
