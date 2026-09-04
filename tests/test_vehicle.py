"""Scheduling and failure handling for the OBDb-driven reader.

Uses a scripted adapter rather than a radio: what matters here is which
requests get sent, how often, and what happens to commands the vehicle never
answers.
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from obd_ev.ble_obd import Elm327Timeout, OBDLinkDown  # noqa: E402
from obd_ev.config import OBDConfig, VehicleConfig  # noqa: E402
from obd_ev.vehicle import VehicleReader  # noqa: E402


SIGNALSET = {
    "commands": [
        {   # fast, answers correctly
            "hdr": "7E4", "rax": "7EC", "cmd": {"22": "0101"}, "freq": 0.25,
            "signals": [{"id": "SOC", "name": "State of charge", "path": "Battery",
                         "fmt": {"bix": 0, "len": 8, "max": 100, "div": 2,
                                 "unit": "percent"}}],
        },
        {   # different ECU, so a header switch is required
            "hdr": "7B3", "rax": "7BB", "cmd": {"22": "0100"}, "freq": 1.0,
            "signals": [{"id": "CABIN_T", "name": "Cabin temp", "path": "Climate",
                         "fmt": {"bix": 0, "len": 8, "max": 100, "add": -40,
                                 "unit": "celsius"}}],
        },
        {   # this vehicle never answers it
            "hdr": "7E4", "rax": "7EC", "cmd": {"22": "9999"}, "freq": 0.25,
            "signals": [{"id": "ABSENT", "name": "Absent", "path": "Battery",
                         "fmt": {"bix": 0, "len": 8, "max": 100, "unit": "percent"}}],
        },
    ]
}


class ScriptedAdapter:
    def __init__(self, replies=None, timeout_on=()):
        self.sent = []
        self.replies = replies or {}
        self.timeout_on = set(timeout_on)
        self.connected = False

    def connect(self):
        self.connected = True

    def pin_protocol(self):
        pass

    def command(self, cmd, timeout=None):
        self.sent.append(cmd)
        if cmd in self.timeout_on:
            raise Elm327Timeout(cmd)
        if cmd.startswith("AT"):
            return "OK"
        return self.replies.get(cmd, "NO DATA")

    def close(self):
        self.connected = False


def make_reader(adapter, **vkw):
    tmp = Path(tempfile.mkdtemp()) / "signalset.json"
    tmp.write_text(json.dumps(SIGNALSET))
    vcfg = VehicleConfig(signalset=str(tmp), **vkw)
    reader = VehicleReader(OBDConfig(), vcfg, adapter=adapter)
    reader.connect()
    return reader


class TestSchedule(unittest.TestCase):
    def test_schema_lists_every_signal_regardless_of_support(self):
        reader = make_reader(ScriptedAdapter())
        self.assertEqual(sorted(reader.field_names()),
                         ["absent_pct", "cabin_temp_c", "state_of_charge_pct"])

    def test_min_period_floors_the_declared_frequency(self):
        reader = make_reader(ScriptedAdapter(), min_period=2.0)
        self.assertTrue(all(i.period >= 2.0 for i in reader._schedule))

    def test_decodes_answers_and_skips_silent_commands(self):
        adapter = ScriptedAdapter(replies={
            "220101": "7EC0462010164",       # 0x64 = 100 -> /2 = 50%
            "220100": "7BB0462010064",       # 0x64 = 100 -> -40 = 60C
        })
        reader = make_reader(adapter)
        values = reader.read()
        self.assertAlmostEqual(values["state_of_charge_pct"], 50.0)
        self.assertAlmostEqual(values["cabin_temp_c"], 60.0)
        self.assertNotIn("absent_pct", values)

    def test_header_is_only_reprogrammed_when_the_ecu_changes(self):
        adapter = ScriptedAdapter(replies={"220101": "7EC0462010164"})
        reader = make_reader(adapter)
        reader.read()
        # Two ECUs are addressed, so exactly two ATSH commands should appear.
        self.assertEqual([c for c in adapter.sent if c.startswith("ATSH")],
                         ["ATSH7E4", "ATSH7B3"])

    def test_unanswered_command_is_retired_after_repeated_no_data(self):
        """'NO DATA' is the normal reply for a PID the trim doesn't have, and
        it must retire the command -- otherwise it burns a round trip forever."""
        adapter = ScriptedAdapter(replies={"220101": "7EC0462010164"})
        reader = make_reader(adapter, disable_after=3, min_period=0.0)
        for _ in range(4):
            for item in reader._schedule:
                item.due_at = 0.0
            reader.read()
        absent = [i for i in reader._schedule if i.command.pid == "9999"][0]
        self.assertTrue(absent.disabled)
        before = len(adapter.sent)
        reader.read()
        self.assertNotIn("229999", adapter.sent[before:])

    def test_a_fully_silent_adapter_raises_link_down(self):
        adapter = ScriptedAdapter(timeout_on={"220101", "220100", "229999"})
        cfg = OBDConfig(max_read_failures=3)
        tmp = Path(tempfile.mkdtemp()) / "s.json"
        tmp.write_text(json.dumps(SIGNALSET))
        reader = VehicleReader(cfg, VehicleConfig(signalset=str(tmp),
                                                  min_period=0.0,
                                                  disable_after=0),
                               adapter=adapter)
        reader.connect()
        with self.assertRaises(OBDLinkDown):
            for _ in range(5):
                for item in reader._schedule:
                    item.due_at = 0.0
                reader.read()

    def test_asleep_vehicle_does_not_permanently_retire_everything(self):
        """A Pi that boots while the car is asleep sees NO DATA on every
        command. Retiring the whole set would mean collecting nothing for the
        rest of the study, so the schedule resets and the link is recycled."""
        adapter = ScriptedAdapter()          # answers NO DATA to everything
        reader = make_reader(adapter, disable_after=2, min_period=0.0)
        with self.assertRaises(OBDLinkDown):
            for _ in range(6):
                for item in reader._schedule:
                    item.due_at = 0.0
                reader.read()
        self.assertFalse(any(i.disabled for i in reader._schedule),
                         "schedule must be reset, not left dead")

        # After the reconnect the car is awake, and collection resumes.
        adapter.replies["220101"] = "7EC0462010164"
        reader.connect()
        self.assertAlmostEqual(reader.read()["state_of_charge_pct"], 50.0)

    def test_path_filters_narrow_collection(self):
        reader = make_reader(ScriptedAdapter(), include_paths=["Battery"])
        self.assertEqual(sorted(reader.field_names()),
                         ["absent_pct", "state_of_charge_pct"])
        reader = make_reader(ScriptedAdapter(), exclude_paths=["Battery"])
        self.assertEqual(reader.field_names(), ["cabin_temp_c"])


if __name__ == "__main__":
    unittest.main()
