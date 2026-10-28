#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Windows 终端 WASD 遥控（直连本机 XRCE agent 的 TCP 控制口）。

先在另一个 Windows 终端运行:
    python -m xrce.agent --host 0.0.0.0 --port 8888
再运行:
    python tools\\teleop_wasd.py

按键: W 前进 / S 后退 / A 左转 / D 右转 / 空格停 / X 退出

实现说明: 直接轮询按键的物理状态（GetAsyncKeyState），不依赖 Windows
的键盘连发。按住方向键时每 0.1 秒刷新一次 0.3 秒的运动指令，松开立即停止。
这样不会出现“走一下、停一下、再连着走”的连发延迟问题。
"""
import ctypes
import os
import socket
import sys
import time

HOST, PORT = "127.0.0.1", 8898
SPEED, TURN = 0.05, 0.3
REFRESH = 0.1       # 按住时每 0.1 秒刷新
CMD_DURATION = 0.3  # 每条指令有效期

VK = {
    "w": 0x57,
    "a": 0x41,
    "s": 0x53,
    "d": 0x44,
    "space": 0x20,
    "x": 0x58,
}

# Windows 控制台默认 GBK，切 UTF-8 避免中文乱码
if os.name == "nt":
    try:
        ctypes.windll.kernel32.SetConsoleOutputCP(65001)
    except Exception:  # noqa: BLE001
        pass
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass


def key_down(vk: int) -> bool:
    return bool(ctypes.windll.user32.GetAsyncKeyState(vk) & 0x8000)


def main() -> int:
    try:
        sock = socket.create_connection((HOST, PORT), timeout=3)
    except OSError:
        print(f"连不上 agent 控制口 {HOST}:{PORT}，请先启动 python -m xrce.agent")
        return 1

    def send(line: str) -> None:
        """发送一行；断线时自动重连一次。"""
        nonlocal sock
        try:
            sock.sendall(line.encode())
        except OSError:
            sock.close()
            sock = socket.create_connection((HOST, PORT), timeout=3)
            sock.sendall(line.encode())

    print("W 前进  S 后退  A 左转  D 右转  空格停  X 退出")
    print("（按住方向键持续运动，松开立即停止）")

    last_send = 0.0
    was_moving = False
    try:
        while True:
            if key_down(VK["x"]):
                break

            if key_down(VK["space"]):
                v, w = 0.0, 0.0
            elif key_down(VK["w"]):
                v, w = SPEED, 0.0
            elif key_down(VK["s"]):
                v, w = -SPEED, 0.0
            elif key_down(VK["a"]):
                v, w = 0.0, TURN
            elif key_down(VK["d"]):
                v, w = 0.0, -TURN
            else:
                v, w = 0.0, 0.0

            now = time.monotonic()
            moving = v != 0.0 or w != 0.0
            if moving:
                if now - last_send >= REFRESH:
                    send(f"{v} {w} {CMD_DURATION}\n")
                    last_send = now
            elif was_moving:
                send("0 0 0.05\n")

            was_moving = moving
            time.sleep(0.02)
    except KeyboardInterrupt:
        pass
    finally:
        try:
            send("0 0 0.05\n")
        except OSError:
            pass
        sock.close()
        print("\n已停车")
    return 0


if __name__ == "__main__":
    sys.exit(main())
