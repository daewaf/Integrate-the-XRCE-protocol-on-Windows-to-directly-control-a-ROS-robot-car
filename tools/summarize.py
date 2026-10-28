"""把 tcpdump 捕获压缩成一行一条的消息摘要。"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from xrce.frame import Message, SUB_NAMES

HEADER_RE = re.compile(r"IP (\S+)\.(\d+) > (\S+)\.(\d+): UDP, length (\d+)")
HEX_RE = re.compile(r"^\s+0x[0-9a-fA-F]+:\s+((?:[0-9a-fA-F]{2,4}\s+){1,8})")


def packets(path):
    cur = None
    with open(path, "r", errors="replace") as fh:
        for line in fh:
            m = HEADER_RE.search(line)
            if m:
                if cur:
                    yield cur
                cur = {"src": m.group(1), "hex": ""}
                continue
            m = HEX_RE.match(line)
            if m and cur is not None:
                cur["hex"] += m.group(1)
    if cur:
        yield cur


def strings(b: bytes, minlen=3):
    return [m.group(0).decode() for m in re.finditer(rb"[\x20-\x7e]{%d,}" % minlen, b)]


def main():
    n = 0
    for p in packets(sys.argv[1]):
        raw = bytes.fromhex("".join(p["hex"].split()))
        if len(raw) >= 28 and (raw[0] >> 4) == 4:
            raw = raw[(raw[0] & 0x0F) * 4 + 8:]
        try:
            msg = Message.decode(raw)
        except Exception:
            continue
        for sm in msg.submessages:
            if sm.id == 1:  # CREATE
                b = sm.payload
                kind = b[4] if len(b) > 4 else -1
                s = strings(b)
                print(f"{n:3d} {'C->A' if p['src'].endswith('.55') else 'A->C'} "
                      f"CREATE obj={b[2]:02X}{b[3]:02X} kind={kind:02X} strings={s}")
            elif sm.id == 7:  # WRITE_DATA
                b = sm.payload
                print(f"{n:3d} {'C->A' if p['src'].endswith('.55') else 'A->C'} "
                      f"WRITE obj={b[2]:02X}{b[3]:02X} seq={msg.sequence_nr} bytes={len(b)-4}")
            elif sm.id == 8:  # READ_DATA
                b = sm.payload
                print(f"{n:3d} {'C->A' if p['src'].endswith('.55') else 'A->C'} "
                      f"READ  obj={b[2]:02X}{b[3]:02X} seq={msg.sequence_nr} bytes={len(b)}")
            elif sm.id == 9:  # DATA
                b = sm.payload
                print(f"{n:3d} {'C->A' if p['src'].endswith('.55') else 'A->C'} "
                      f"DATA  obj={b[2]:02X}{b[3]:02X} seq={msg.sequence_nr} bytes={len(b)-4}")
            elif sm.id == 2:  # GET_INFO
                b = sm.payload
                print(f"{n:3d} {'C->A' if p['src'].endswith('.55') else 'A->C'} "
                      f"GETINFO obj={b[2]:02X}{b[3]:02X} mask={b[4:8].hex()}")
            elif sm.id == 6:
                print(f"{n:3d} {'C->A' if p['src'].endswith('.55') else 'A->C'} INFO")
            elif sm.id == 5:
                b = sm.payload
                print(f"{n:3d} {'C->A' if p['src'].endswith('.55') else 'A->C'} "
                      f"STATUS obj={b[2]:02X}{b[3]:02X}")
            n += 1


if __name__ == "__main__":
    main()
