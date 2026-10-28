#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""FishBot 一键启动：后台运行纯 Python XRCE agent，前台进入 WASD 遥控。

用法:
    python start_fishbot.py
    python start_fishbot.py --check      # 只启动并检查 agent，不进入遥控

退出方式: 在遥控界面按 X 或 Ctrl+C，agent 会被自动关闭。
如果已有 agent 在 8898 控制口上运行，会直接复用，不会重复启动。
"""
import argparse
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

# Windows 控制台默认 GBK，切 UTF-8 避免中文乱码
if os.name == "nt":
    try:
        import ctypes

        ctypes.windll.kernel32.SetConsoleOutputCP(65001)
    except Exception:  # noqa: BLE001
        pass
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

ROOT = Path(__file__).resolve().parent
TELEOP = ROOT / "tools" / "teleop_wasd.py"
AGENT_LOG = ROOT / "agent_runtime.log"
CONTROL_PORT = 8898
UDP_PORT = 8888


def port_open(host: str, port: int, timeout: float = 0.3) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(timeout)
        return s.connect_ex((host, port)) == 0


def local_ip() -> str:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
    except OSError:
        return "未知"


def start_agent() -> subprocess.Popen | None:
    """启动 agent；若已有实例在控制口上运行则返回 None。"""
    if port_open("127.0.0.1", CONTROL_PORT):
        print(f"检测到已有 agent 在 127.0.0.1:{CONTROL_PORT}，直接复用")
        return None

    log = open(AGENT_LOG, "w", encoding="utf-8", errors="replace")
    creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    proc = subprocess.Popen(
        [sys.executable, "-m", "xrce.agent",
         "--host", "0.0.0.0", "--port", str(UDP_PORT)],
        cwd=str(ROOT),
        stdout=log,
        stderr=subprocess.STDOUT,
        creationflags=creationflags,
    )
    print(f"agent 启动中（PID {proc.pid}）...")
    for _ in range(50):  # 最多等 10 秒
        if proc.poll() is not None:
            break
        if port_open("127.0.0.1", CONTROL_PORT):
            print("agent 已就绪：UDP 8888 / TCP 8898")
            return proc
        time.sleep(0.2)

    print("agent 启动失败，日志尾部：")
    try:
        print(AGENT_LOG.read_text(encoding="utf-8", errors="replace")[-1500:])
    except OSError:
        pass
    if proc.poll() is None:
        proc.terminate()
    return None


def stop_agent(proc: subprocess.Popen | None) -> None:
    if proc is None or proc.poll() is not None:
        return
    proc.terminate()
    try:
        proc.wait(timeout=3)
    except subprocess.TimeoutExpired:
        proc.kill()


def main() -> int:
    ap = argparse.ArgumentParser(description="FishBot 一键启动")
    ap.add_argument("--check", action="store_true", help="只检查和启动 agent，不进入遥控")
    args = ap.parse_args()

    print(f"本机 IP: {local_ip()}  （主控板“上位机 IP”填这个，端口 {UDP_PORT}）")
    agent = start_agent()
    if agent is None and not port_open("127.0.0.1", CONTROL_PORT):
        return 1

    try:
        if args.check:
            print("检查通过：agent 可用")
            return 0
        print("进入 WASD 遥控（X 退出）\n")
        return subprocess.run([sys.executable, str(TELEOP)], cwd=str(ROOT)).returncode
    finally:
        stop_agent(agent)
        print("agent 已停止" if agent is not None else "复用的 agent 保持运行")


if __name__ == "__main__":
    sys.exit(main())
