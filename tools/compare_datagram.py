"""对比两份 tcpdump 里第一条 36 字节载荷的完整 IP 数据报。"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from parse_tcpdump import parse


def first_info_datagram(path):
    for p in parse(path):
        raw = bytes.fromhex("".join(p["hex"].split()))
        if len(raw) >= 28 and raw[0] == 0x45 and int.from_bytes(raw[2:4], "big") == 64:
            if raw[9] == 17:  # UDP
                return raw
    return b""


def main():
    a = first_info_datagram(sys.argv[1])
    b = first_info_datagram(sys.argv[2])
    print("official:", a.hex(" "))
    print("ours    :", b.hex(" "))
    print("equal:", a == b)
    for i, (x, y) in enumerate(zip(a, b)):
        if x != y:
            print(f"  byte {i:02d}: {x:02X} != {y:02X}")


if __name__ == "__main__":
    main()
