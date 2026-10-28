"""把十六进制报文解析成 XRCE 消息结构，便于对照抓包。"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from xrce.agent import hexdump
from xrce.frame import Message, SUB_NAMES


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("hex", help="十六进制字符串，例如 8000000000071B00...")
    args = ap.parse_args()
    raw = bytes.fromhex(args.hex.replace(" ", "").replace("\n", ""))
    print(hexdump(raw))
    try:
        msg = Message.decode(raw)
    except Exception as exc:  # noqa: BLE001
        print("解析失败:", exc)
        return 1
    print(repr(msg))
    for i, sm in enumerate(msg.submessages):
        print(f"  [{i}] {SUB_NAMES.get(sm.id, sm.id)} flags=0x{sm.flags:02X} len={len(sm.payload)}")
        print(hexdump(sm.payload, "      "))
    return 0


if __name__ == "__main__":
    sys.exit(main())
