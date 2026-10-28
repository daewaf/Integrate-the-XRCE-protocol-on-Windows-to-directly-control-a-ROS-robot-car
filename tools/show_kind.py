"""打印指定 ObjectKind 的 CREATE 报文完整载荷。"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from parse_tcpdump import parse
from xrce.agent import hexdump
from xrce.frame import Message


def main():
    path = sys.argv[1]
    want = int(sys.argv[2], 0)
    for p in parse(path):
        raw = bytes.fromhex("".join(p["hex"].split()))
        if len(raw) >= 28 and (raw[0] >> 4) == 4:
            raw = raw[(raw[0] & 0x0F) * 4 + 8:]
        try:
            msg = Message.decode(raw)
        except Exception:
            continue
        for sm in msg.submessages:
            if sm.id == 1 and len(sm.payload) > 4 and sm.payload[4] == want:
                b = sm.payload
                print(f"obj={b[2]:02X}{b[3]:02X} kind={b[4]:02X} len={len(b)}")
                print(hexdump(b))
                print()


if __name__ == "__main__":
    main()
