import unittest

from xrce.cdr import CDRReader, CDRWriter, twist_cdr
from xrce.frame import (
    FLAG_ENDIANNESS,
    SESSION_NONE_WITHOUT_CLIENT_KEY,
    STREAM_NONE,
    Message,
    Submessage,
    SUB_CREATE_CLIENT,
)


class FrameTests(unittest.TestCase):
    def test_header_layout_matches_spec_b1(self):
        msg = Message(
            session_id=SESSION_NONE_WITHOUT_CLIENT_KEY,
            stream_id=STREAM_NONE,
            sequence_nr=0,
            # 规范 B.1 的示例用 flags=0x07（reuse|replace|little endian）
            submessages=[Submessage(SUB_CREATE_CLIENT, b"\x00" * 14, flags=0x07)],
        )
        raw = msg.encode()
        self.assertEqual(raw[:8], bytes.fromhex("80000000" "00070E00"))
        self.assertEqual(len(raw), 4 + 4 + 14)

    def test_client_key_present_when_session_le_127(self):
        msg = Message(session_id=0x01, stream_id=0x80, sequence_nr=7,
                      client_key=0x55667788,
                      submessages=[Submessage(SUB_CREATE_CLIENT, b"")])
        raw = msg.encode()
        self.assertEqual(raw[:8], bytes.fromhex("01800700" "88776655"))

    def test_roundtrip(self):
        msg = Message(session_id=0xDD, stream_id=0x80, sequence_nr=3,
                      submessages=[Submessage(1, b"abcd"), Submessage(7, b"xy")])
        back = Message.decode(msg.encode())
        self.assertEqual(back.session_id, 0xDD)
        self.assertEqual(back.stream_id, 0x80)
        self.assertEqual([s.payload for s in back.submessages], [b"abcd", b"xy"])

    def test_submessage_header_little_endian(self):
        sm = Submessage(1, b"abcd", FLAG_ENDIANNESS)
        self.assertEqual(sm.encode(), bytes.fromhex("01010400") + b"abcd")


class CDRTests(unittest.TestCase):
    def test_twist_is_48_bytes(self):
        raw = twist_cdr(0.1, -0.5)
        self.assertEqual(len(raw), 48)
        r = CDRReader(raw)
        self.assertAlmostEqual(r.f64(), 0.1)
        r.f64(); r.f64()
        self.assertEqual(r.f64(), 0.0)
        self.assertEqual(r.f64(), 0.0)
        self.assertAlmostEqual(r.f64(), -0.5)

    def test_string_encoding(self):
        w = CDRWriter().string("AB")
        self.assertEqual(w.bytes(), bytes.fromhex("03000000") + b"AB\x00")
        self.assertEqual(CDRReader(w.bytes()).string(), "AB")

    def test_dheader(self):
        self.assertEqual(CDRWriter().dheader(12).bytes(), bytes.fromhex("0C000080"))


if __name__ == "__main__":
    unittest.main()
