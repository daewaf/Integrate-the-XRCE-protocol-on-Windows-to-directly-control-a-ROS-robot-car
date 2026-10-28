"""对比两次抓包里 INFO 子消息的字节。"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from parse_tcpdump import parse
from xrce.frame import Message


def info_payload(path):
    for p in parse(path):
        raw = bytes.fromhex("".join(p["hex"].split()))
        if len(raw) >= 28 and (raw[0] >> 4) == 4:
            raw = raw[(raw[0] & 0x0F) * 4 + 8:]
        try:
            msg = Message.decode(raw)
        except Exception:
            continue
        for sm in msg.submessages:
            if sm.id == 6:
                return sm.payload
    return b""


def main():
    a = info_payload(sys.argv[1])
    b = info_payload(sys.argv[2])
    print("official:", a.hex(" "))
    print("ours    :", b.hex(" "))
    print("equal:", a == b, "len:", len(a), len(b))
    for i, (x, y) in enumerate(zip(a, b)):
        if x != y:
            print(f"diff at byte {i}: {x:02X} != {y:02X}")


if __name__ == "__main__":
    main()
