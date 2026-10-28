"""自动模拟按住 W 1.2 秒，验证 teleop_wasd 的持续控制与松开停止。"""
import ctypes
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
user32 = ctypes.windll.user32

tele = subprocess.Popen(
    [sys.executable, str(ROOT / "tools" / "teleop_wasd.py")],
    cwd=str(ROOT),
)
time.sleep(1.2)

print("[sim] W down")
user32.keybd_event(0x57, 0, 0, 0)
time.sleep(1.2)
print("[sim] W up")
user32.keybd_event(0x57, 0, 2, 0)
time.sleep(0.6)

print("[sim] X down/up (exit)")
user32.keybd_event(0x58, 0, 0, 0)
time.sleep(0.1)
user32.keybd_event(0x58, 0, 2, 0)
time.sleep(1.0)

print("[sim] teleop exit code:", tele.poll())
if tele.poll() is None:
    tele.terminate()
