"""Runs the real CLI over real fixtures, no mocks.

Every rule test uses two files: tests/fixtures/clean.css (clears every
rule) as the pass case, and a fixture that plants exactly one violation
as the fail case. The assertion is on the exact verdict the report gives
back for that rule, read from --json.
"""
from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).parent.parent
SCRIPT = ROOT / "motion_bar.py"
FIXTURES = Path(__file__).parent / "fixtures"
CLEAN = FIXTURES / "clean.css"


def run(args: list, cwd: Optional[Path] = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True, text=True, cwd=str(cwd or ROOT),
    )


def run_json(path: Path) -> dict:
    result = run([str(path), "--json"])
    return json.loads(result.stdout)


class RuleTestCase(unittest.TestCase):
    """Base class: subclasses set RULE and FIXTURE, get a fail + pass test for free."""

    RULE = ""
    FIXTURE = ""
    EXPECT_BLOCKING = False

    def setUp(self) -> None:
        if not self.RULE:
            self.skipTest("base class carries no fixture of its own")

    def test_fail_fixture_triggers_the_rule(self) -> None:
        fixture = FIXTURES / self.FIXTURE
        report = run_json(fixture)
        verdict = report["rules"][self.RULE]["verdict"]
        self.assertIn(verdict, ("FAIL", "WARN"), f"{self.RULE} did not fire on {fixture}")
        if self.EXPECT_BLOCKING:
            self.assertEqual(verdict, "FAIL", f"{self.RULE} should be blocking on {fixture}")
        findings = report["rules"][self.RULE]["findings"]
        self.assertTrue(findings, f"{self.RULE} reported no findings on {fixture}")
        if self.RULE != "no-reduced-motion":  # that rule reports "(scanned set)", not a file
            self.assertTrue(findings[0]["file"].endswith(self.FIXTURE))
        self.assertGreaterEqual(findings[0]["line"], 0)

    def test_clean_fixture_clears_the_rule(self) -> None:
        report = run_json(CLEAN)
        self.assertEqual(report["rules"][self.RULE]["verdict"], "PASS")
        self.assertEqual(report["rules"][self.RULE]["findings"], [])


class TestEaseIn(RuleTestCase):
    RULE = "ease-in"
    FIXTURE = "ease-in.css"
    EXPECT_BLOCKING = True


class TestTransitionAll(RuleTestCase):
    RULE = "transition-all"
    FIXTURE = "transition-all.css"
    EXPECT_BLOCKING = True


class TestScaleZero(RuleTestCase):
    RULE = "scale-zero"
    FIXTURE = "scale-zero.css"
    EXPECT_BLOCKING = True


class TestScaleZeroProp(RuleTestCase):
    RULE = "scale-zero-prop"
    FIXTURE = "scale-zero-prop.css"


class TestLayoutProp(RuleTestCase):
    RULE = "layout-prop"
    FIXTURE = "layout-prop.css"


class TestDurationCeiling(RuleTestCase):
    RULE = "duration-ceiling"
    FIXTURE = "duration-ceiling.css"
    EXPECT_BLOCKING = True


class TestLinearEasing(RuleTestCase):
    RULE = "linear-easing"
    FIXTURE = "linear-easing.css"


class TestHighFrequencyAnimation(RuleTestCase):
    RULE = "high-frequency-animation"
    FIXTURE = "high-frequency-animation.css"
    EXPECT_BLOCKING = True


class TestInfiniteLoop(RuleTestCase):
    RULE = "infinite-loop"
    FIXTURE = "infinite-loop.css"


class TestFramerShorthand(RuleTestCase):
    RULE = "framer-shorthand"
    FIXTURE = "framer-shorthand.jsx"


class TestNoReducedMotion(RuleTestCase):
    RULE = "no-reduced-motion"
    FIXTURE = "no-reduced-motion.css"


class TestKeyframesLayoutProp(unittest.TestCase):
    """layout-prop also fires inside @keyframes, not just on `transition:`."""

    def test_keyframes_animating_top_is_flagged(self) -> None:
        report = run_json(ROOT / "demo" / "slop.css")
        findings = report["rules"]["layout-prop"]["findings"]
        self.assertTrue(any("slop.css" in f["file"] for f in findings))


class TestConstantMotionIsExempt(unittest.TestCase):
    """linear + a long duration on a progress/loader element is not a violation:
    demo/clean.css carries exactly this case and must stay fully clean."""

    def test_progress_bar_is_not_flagged(self) -> None:
        report = run_json(ROOT / "demo" / "clean.css")
        self.assertEqual(report["summary"]["findings"], 0)


class TestExitCodes(unittest.TestCase):
    def test_clean_file_exits_zero(self) -> None:
        result = run([str(CLEAN)])
        self.assertEqual(result.returncode, 0)

    def test_dirty_file_exits_one(self) -> None:
        result = run([str(FIXTURES / "ease-in.css")])
        self.assertEqual(result.returncode, 1)

    def test_demo_slop_files_exit_one(self) -> None:
        result = run(["demo/slop.css", "demo/slop.html"])
        self.assertEqual(result.returncode, 1)

    def test_demo_clean_file_exits_zero(self) -> None:
        result = run(["demo/clean.css"])
        self.assertEqual(result.returncode, 0)


class TestJsonOutput(unittest.TestCase):
    def test_json_shape(self) -> None:
        report = run_json(FIXTURES / "duration-ceiling.css")
        self.assertIn("target", report)
        self.assertIn("rules", report)
        self.assertIn("summary", report)
        self.assertEqual(report["summary"]["rules_checked"], 11)
        self.assertGreater(report["summary"]["findings"], 0)
        self.assertGreater(report["summary"]["blocking"], 0)
        for name, rule in report["rules"].items():
            self.assertIsInstance(rule["number"], int)
            self.assertIn(rule["verdict"], ("PASS", "WARN", "FAIL"))
            self.assertIsInstance(rule["findings"], list)

    def test_json_is_valid_on_a_clean_file(self) -> None:
        report = run_json(CLEAN)
        self.assertEqual(report["summary"]["findings"], 0)
        self.assertEqual(report["summary"]["blocking"], 0)


class TestUsageErrors(unittest.TestCase):
    def test_no_paths_and_no_changed_exits_two(self) -> None:
        result = run([])
        self.assertEqual(result.returncode, 2)
        self.assertIn("give at least one path", result.stderr)

    def test_missing_path_exits_two(self) -> None:
        result = run(["no/such/file.css"])
        self.assertEqual(result.returncode, 2)

    def test_missing_rules_config_exits_two(self) -> None:
        result = run([str(CLEAN), "--rules", "no/such/rules.json"])
        self.assertEqual(result.returncode, 2)


class TestChangedFlag(unittest.TestCase):
    def test_changed_file_list_is_scanned(self) -> None:
        changed = FIXTURES / ".changed-list.txt"
        changed.write_text(f"{CLEAN}\n")
        try:
            result = run(["--changed", str(changed)])
            self.assertEqual(result.returncode, 0)
            self.assertIn(str(CLEAN.name), result.stdout)
        finally:
            changed.unlink()

    def test_changed_skips_non_ui_files(self) -> None:
        changed = FIXTURES / ".changed-list-2.txt"
        readme = ROOT / "README.md"
        changed.write_text(f"{readme}\n")
        try:
            result = run(["--changed", str(changed)])
            self.assertEqual(result.returncode, 0)
            self.assertNotIn("README.md", result.stdout)
        finally:
            changed.unlink()


class TestDirectoryWalk(unittest.TestCase):
    def test_directory_argument_walks_ui_files(self) -> None:
        result = run(["demo"])
        self.assertIn("clean.css", result.stdout)
        self.assertIn("slop.css", result.stdout)
        self.assertEqual(result.returncode, 1)  # slop.css is in the mix


if __name__ == "__main__":
    unittest.main()
