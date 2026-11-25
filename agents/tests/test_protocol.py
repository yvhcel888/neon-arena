import unittest

from arena_agent.protocol import DIRS, PROTOCOL, decode, encode


class ProtocolTests(unittest.TestCase):
    def test_roundtrip(self):
        msg = {"type": "join", "protocol": PROTOCOL, "name": "A"}
        self.assertEqual(decode(encode(msg)), msg)

    def test_encode_is_compact_utf8_ndjson(self):
        self.assertEqual(
            encode({"type": "join", "name": "霓虹"}),
            '{"type":"join","name":"霓虹"}\n'.encode("utf-8"),
        )

    def test_reject_bad_json(self):
        with self.assertRaises(ValueError):
            decode(b"{not json}")

    def test_reject_invalid_utf8(self):
        with self.assertRaises(ValueError):
            decode(b"\xff")

    def test_reject_non_object(self):
        with self.assertRaises(ValueError):
            decode(b"[]")

    def test_reject_missing_or_invalid_type(self):
        for line in (b"{}", b'{"type":""}', b'{"type":1}'):
            with self.subTest(line=line), self.assertRaises(ValueError):
                decode(line)

    def test_directions(self):
        self.assertEqual(
            DIRS, {"n": (0, -1), "e": (1, 0), "s": (0, 1), "w": (-1, 0)},
        )
        self.assertEqual(PROTOCOL, 1)


if __name__ == "__main__":
    unittest.main()
