"""Replays demo/transcript.json and checks demo/terminal.svg against it.

The picture in the README is drawn from the transcript, so the transcript
has to be the real thing: every command is run with bash in a throwaway
copy of the checkout, and its combined output and exit code must match
what is recorded. Set UPDATE_DEMO_TRANSCRIPT=1 to rewrite the transcript
from a real run instead of asserting against it.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).parent.parent
TRANSCRIPT = ROOT / "demo" / "transcript.json"
SVG = ROOT / "demo" / "terminal.svg"
CHECKOUT = "/path/to/checkout"
SVG_NS = {"svg": "http://www.w3.org/2000/svg"}
ELLIPSIS = "…"
COPY_SKIPS = shutil.ignore_patterns(".git", "__pycache__", "*.egg-info", "build", "dist")


def run_entry(cmd: str, cwd: Path) -> tuple:
    """Run one transcript command line, with stderr interleaved into stdout."""
    proc = subprocess.run(
        ["bash", "-c", cmd], cwd=str(cwd), text=True,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
    )
    return normalize(proc.stdout, cwd), proc.returncode


def normalize(out: str, cwd: Path) -> str:
    """The copy's location is the only machine-specific text a scan can print
    (macOS resolves /var to /private/var, so both forms are replaced)."""
    for form in (str(cwd.resolve()), str(cwd)):
        out = out.replace(form, CHECKOUT)
    return out.rstrip("\n")


def replay_all() -> list:
    entries = json.loads(TRANSCRIPT.read_text(encoding="utf-8"))
    with tempfile.TemporaryDirectory() as tmp:
        copy = Path(tmp) / "motion-bar"
        shutil.copytree(ROOT, copy, ignore=COPY_SKIPS)
        replayed = []
        for entry in entries:
            out, status = run_entry(entry["cmd"], copy)
            replayed.append({"cmd": entry["cmd"], "out": out, "status": status})
        return replayed


class TestDemoTranscript(unittest.TestCase):
    """demo/transcript.json is a receipt: it holds what the commands print."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.recorded = json.loads(TRANSCRIPT.read_text(encoding="utf-8"))
        cls.replayed = replay_all()
        if os.environ.get("UPDATE_DEMO_TRANSCRIPT"):
            TRANSCRIPT.write_text(json.dumps(cls.replayed, indent=2) + "\n", encoding="utf-8")
            cls.recorded = cls.replayed

    def test_every_command_still_prints_what_was_recorded(self) -> None:
        for recorded, replayed in zip(self.recorded, self.replayed):
            with self.subTest(cmd=recorded["cmd"]):
                self.assertEqual(replayed["out"], recorded["out"])
                self.assertEqual(replayed["status"], recorded["status"])

    def test_picture_rows_come_from_the_transcript(self) -> None:
        cmds = [e["cmd"] for e in self.recorded]
        out_lines = [line for e in self.recorded for line in e["out"].splitlines()]
        for kind, row in svg_rows():
            with self.subTest(row=row):
                shown = row[:-1] if row.endswith(ELLIPSIS) else row
                if kind == "cmd":
                    chunk = shown[:-2] if shown.endswith(" \\") else shown
                    self.assertTrue(any(chunk in cmd for cmd in cmds),
                                    f"command row is in no transcript command: {row!r}")
                else:
                    self.assertTrue(any(line.startswith(shown) for line in out_lines),
                                    f"output row is in no transcript output: {row!r}")


def svg_rows() -> list:
    """(kind, text) for every session row of the picture, in order. A command
    row is written as a prompt tspan plus the command; a wrapped command
    continues on a row of its own, indented four spaces."""
    root = ET.parse(SVG).getroot()
    rows = []
    for text_el in root.findall("svg:text", SVG_NS):
        if text_el.get("font-size"):
            continue  # the window title bar, the one row with its own size
        tspans = text_el.findall("svg:tspan", SVG_NS)
        if tspans:
            rows.append(("cmd", tspans[-1].text or ""))
        elif text_el.get("class") == "cmd":
            rows.append(("cmd", (text_el.text or "")[4:]))
        else:
            rows.append(("out", text_el.text or ""))
    return rows


if __name__ == "__main__":
    unittest.main()
