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

    def test_the_picture_shows_whole_entries_in_order(self) -> None:
        """No row invented, none missing, none out of order.

        The transcript is walked in step with the drawing: a command's rows
        must rejoin to the recorded command, every one of its non-empty output
        lines must be the next row, and the picture may stop only between
        commands, with nothing drawn left over.
        """
        rows = svg_rows()
        self.assertTrue(rows, "the picture has no session rows")
        index = 0
        for entry in self.recorded:
            if index == len(rows):
                break  # the picture holds whole entries, then stops
            kind, text = rows[index]
            self.assertEqual(kind, "cmd", f"row {index + 1} should open {entry['cmd']}")
            chunks = [text]
            index += 1
            while index < len(rows) and rows[index][0] == "cmd-cont":
                chunks.append(rows[index][1])
                index += 1
            self.assertEqual(rejoin(chunks), entry["cmd"],
                             "the command rows do not rebuild the recorded command")
            for line in (l for l in entry["out"].splitlines() if l.strip()):
                self.assertLess(index, len(rows),
                                f"the picture stops inside {entry['cmd']}, before {line!r}")
                kind, shown = rows[index]
                self.assertEqual(kind, "out", f"row {index + 1} should be output line {line!r}")
                self.assertTrue(shows_whole(shown, line),
                                f"row {index + 1} is {shown!r}, expected {line!r} whole or "
                                "end-trimmed with one ellipsis")
                index += 1
        self.assertEqual(index, len(rows),
                         f"{len(rows) - index} drawn row(s) the transcript does not account for")


def rejoin(chunks: list) -> str:
    """Undo the drawing's wrapping: a wrapped row ends in " \\" and the chunks
    rejoin with the one space the break ate."""
    return " ".join(c[:-2] if c.endswith(" \\") else c for c in chunks)


def shows_whole(shown: str, line: str) -> bool:
    """A row is the output line itself, or that line cut once at the end."""
    if shown == line:
        return True
    head = shown[: -len(ELLIPSIS)]
    return (shown.endswith(ELLIPSIS) and shown.count(ELLIPSIS) == 1
            and len(head) < len(line) and line.startswith(head))


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
            rows.append(("cmd-cont", (text_el.text or "")[4:]))
        else:
            rows.append(("out", text_el.text or ""))
    return rows


if __name__ == "__main__":
    unittest.main()
