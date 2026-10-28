"""解析 `tcpdump -X` 文本输出，提取 UDP 载荷并解码 XRCE 消息。"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from xrce.agent import hexdump
from xrce.frame import Message, SUB_NAMES

HEADER_RE = re.compile(r"IP (\S+)\.(\d+) > (\S+)\.(\d+): UDP, length (\d+)")
HEX_RE = re.compile(r"^\s+0x[0-9a-fA-F]+:\s+((?:[0-9a-fA-F]{2,4}\s+){1,8})")


def parse(path: str):
    packets = []
    current = None
    with open(path, "r", errors="replace") as fh:
        for line in fh:
            m = HEADER_RE.search(line)
            if m:
                if current:
                    packets.append(current)
                current = {
                    "src": (m.group(1), int(m.group(2))),
                    "dst": (m.group(3), int(m.group(4))),
                    "len": int(m.group(5)),
                    "hex": "",
                }
                continue
            m = HEX_RE.match(line)
            if m and current is not None:
                current["hex"] += m.group(1).strip()
    if current:
        packets.append(current)
    return packets


def main() -> int:
    path = sys.argv[1] if len(sys.argv) > 1 else "/tmp/cap.txt"
    pkts = parse(path)
    print(f"packets: {len(pkts)}")
    for i, p in enumerate(pkts):
        raw = bytes.fromhex("".join(p["hex"].split()))
        # tcpdump -i any 在部分平台会包含 IP/UDP 头，剥掉再解码
        if len(raw) >= 28 and (raw[0] >> 4) == 4:
            ihl = (raw[0] & 0x0F) * 4
            raw = raw[ihl + 8:]
        direction = "CLIENT->AGENT" if p["src"][0].endswith(".55") else "AGENT->CLIENT"
        print(f"\n#{i} {direction} {p['src'][0]}:{p['src'][1]} -> {p['dst'][0]}:{p['dst'][1]} "
              f"len={len(raw)}")
        try:
            msg = Message.decode(raw)
            print(repr(msg))
            for sm in msg.submessages:
                print(f"  {SUB_NAMES.get(sm.id, sm.id)} flags=0x{sm.flags:02X} "
                      f"payload={len(sm.payload)}B")
                print(hexdump(sm.payload, "    "))
        except Exception as exc:  # noqa: BLE001
            print("decode failed:", exc)
            print(hexdump(raw, "  "))
    return 0


if __name__ == "__main__":
    sys.exit(main())
