"""Decoder tests against vectors published by OBDb itself.

`tests/fixtures/obdb_vectors.json` holds real commands and captured adapter
responses lifted from the per-vehicle repos' own test suites, together with the
values OBDb says they decode to. Regenerate or widen the sweep with
`scripts/validate_obdb.py`, which runs the same check against every test case
in every upstream repo.
"""

import json
import unittest
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from obd_ev.obdb import Command, SignalSet, reassemble  # noqa: E402

FIXTURES = Path(__file__).parent / "fixtures" / "obdb_vectors.json"


def _frames(can_id: str, payload: bytes) -> str:
    """Encode a payload the way an ELM327 prints it with ATH1/ATCAF0."""
    if len(payload) <= 7:
        return f"{can_id}{len(payload):01X}{payload.hex().upper()}"
    lines = [f"{can_id}1{len(payload):03X}{payload[:6].hex().upper()}"]
    rest, seq = payload[6:], 1
    while rest:
        chunk, rest = rest[:7], rest[7:]
        lines.append(f"{can_id}2{seq:01X}{chunk.hex().upper()}")
        seq = (seq + 1) % 16
    return "\n".join(lines)


def close(a, b):
    # Fixture values are rounded to five decimal places upstream.
    return abs(a - b) <= 6e-6 + abs(b) * 1e-4


class TestOBDbVectors(unittest.TestCase):
    def test_published_vectors(self):
        vectors = json.loads(FIXTURES.read_text())
        self.assertGreater(len(vectors), 0)
        checked = 0
        for entry in vectors:
            cmd = Command.from_json(entry["command"])
            for case in entry["cases"]:
                got = cmd.decode_response(case["response"])
                for sig, want in case["expected"].items():
                    with self.subTest(vehicle=entry["vehicle"],
                                      command=entry["command_id"], signal=sig):
                        have = got.get(sig)
                        self.assertIsNotNone(
                            have, f"{sig} did not decode from {entry['command_id']}")
                        if isinstance(want, (int, float)):
                            self.assertTrue(
                                close(have, want),
                                f"{sig}: expected {want}, decoded {have}")
                        else:
                            self.assertEqual(have, want)
                    checked += 1
        self.assertGreater(checked, 250)


class TestReassembly(unittest.TestCase):
    def test_single_frame(self):
        # `06 41 0C 1A F8 00 00` -> six payload bytes.
        packets = reassemble("7E80641 0C1AF80000")
        self.assertEqual(packets["7E8"], [bytes.fromhex("410C1AF80000")])

    def test_multi_frame_is_truncated_to_declared_length(self):
        text = "\n".join([
            "738102262F010FFFF00",
            "7382100000000000000",
            "73822000001005D7FC3",
            "738237FF07F0000016C",
            "738243A3505410D7E13",
        ])
        payload = reassemble(text)["738"][0]
        self.assertEqual(len(payload), 0x22)
        self.assertTrue(payload.startswith(bytes.fromhex("62F010")))

    def test_two_messages_on_one_can_id_are_both_kept(self):
        """A stale reply sitting in the adapter buffer must not clobber the
        real answer, and must not be mistaken for it either."""
        text = "\n".join([
            "7EC1027620104FFFFFF",
            "7EC21FFC1C1C1C1C1C1",
            "7EC22C1C1C1C1C1C1C1",
            "7EC23C1C1C1C1C1C1C1",
            "7EC24C1C1C1C1C1C1C1",
            "7EC25C1C1C1C1C1AAAA",
            "7EC0441310000",
        ])
        packets = reassemble(text)
        self.assertEqual(len(packets["7EC"]), 2)
        self.assertEqual(len(packets["7EC"][0]), 0x27)
        self.assertEqual(packets["7EC"][1], bytes.fromhex("41310000"))

    def test_newest_matching_message_wins(self):
        cmd = Command.from_json({
            "hdr": "7E4", "rax": "7EC", "cmd": {"22": "0104"},
            "signals": [{"id": "CELL", "name": "cell",
                         "fmt": {"bix": 32, "len": 8, "max": 5.1,
                                 "div": 50, "unit": "volts"}}],
        })
        # bix 32 is the fifth byte after the `62 01 04` echo.
        stale = _frames("7EC", bytes.fromhex("620104FFFFFFFF") + bytes([0xC1]) * 32)
        fresh = _frames("7EC", bytes.fromhex("620104FFFFFFFF") + bytes([0xC4]) * 32)
        self.assertAlmostEqual(cmd.decode_response(stale)["CELL"], 0xC1 / 50)
        self.assertAlmostEqual(
            cmd.decode_response(stale + "\n" + fresh)["CELL"], 0xC4 / 50)

    def test_ignores_prompt_and_noise_lines(self):
        packets = reassemble("SEARCHING...\n7E80641 0C1AF80000\n>")
        self.assertEqual(packets["7E8"], [bytes.fromhex("410C1AF80000")])


class TestYearFilter(unittest.TestCase):
    def test_filter_selects_commands_by_model_year(self):
        ss = SignalSet.from_json({"commands": [
            {"cmd": {"22": "0101"}, "filter": {"from": 2022}, "signals": []},
            {"cmd": {"22": "0102"}, "filter": {"to": 2021}, "signals": []},
            {"cmd": {"22": "0103"}, "signals": []},
        ]})
        self.assertEqual(
            sorted(c.pid for c in ss.for_year(2024).commands), ["0101", "0103"])
        self.assertEqual(
            sorted(c.pid for c in ss.for_year(2019).commands), ["0102", "0103"])
        # No year configured means no filtering.
        self.assertEqual(len(ss.for_year(None).commands), 3)


if __name__ == "__main__":
    unittest.main()
