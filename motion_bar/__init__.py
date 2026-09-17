"""Scan UI code for the motion violations a design review would flag.

Eleven named rules, each machine-checkable from source: no rendering, no
browser, no JavaScript execution. Every finding names the file, the line,
and the exact offending string. Rules informed by Emil Kowalski's
published animation guidance (see README credits); the numeric ceilings
and selector lists live in motion_bar/rules.json, not in this file.

Stdlib only, Python 3.9+. Exit 0 on a clean scan, 1 on any finding,
2 on a usage error.

Usage:
    python3 -m motion_bar <paths...> [--rules rules.json] [--json]
    python3 -m motion_bar --changed files.txt [--rules ...] [--json]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Iterator, Optional

__version__ = "1.0.0"

DEFAULT_RULES_PATH = Path(__file__).parent / "rules.json"
UI_EXT = {".css", ".scss", ".less", ".sass", ".html", ".htm", ".js", ".jsx",
          ".ts", ".tsx", ".mjs", ".cjs", ".vue", ".svelte"}
SKIP_DIRS = {"node_modules", "dist", "build", ".next", ".git", "vendor", "coverage"}
CONTEXT_BEFORE = 400

RULE_NAMES = {
    1: "ease-in",
    2: "transition-all",
    3: "scale-zero",
    4: "scale-zero-prop",
    5: "layout-prop",
    6: "duration-ceiling",
    7: "linear-easing",
    8: "high-frequency-animation",
    9: "infinite-loop",
    10: "framer-shorthand",
    11: "no-reduced-motion",
}
RULE_TITLES = {
    "ease-in": "ease-in easing",
    "transition-all": "unbounded transition-all",
    "scale-zero": "entrance/exit from scale(0)",
    "scale-zero-prop": "scale: 0 as a property value",
    "layout-prop": "layout-property animation",
    "duration-ceiling": "duration past its ceiling",
    "linear-easing": "linear easing on non-constant motion",
    "high-frequency-animation": "animation on a high-frequency element",
    "infinite-loop": "infinite animation outside a loader",
    "framer-shorthand": "Framer Motion x/y shorthand",
    "no-reduced-motion": "missing prefers-reduced-motion guard",
}
BLOCKING_RULES = {"ease-in", "transition-all", "scale-zero", "high-frequency-animation"}

I = re.IGNORECASE
EASE_IN = re.compile(r'(?<![-\w])ease-in(?!-out)(?![-\w])|["\']easeIn["\']', I)
TRANSITION_ALL = re.compile(
    r'transition(?:-property)?\s*:[^;{}"\'\n]*(?<![-\w])all(?![-\w])(?!\s*:)'
    r'|transition(?:-property)?\s*:\s*\n\s*all(?![-\w])(?!\s*:)'
    r'|transition(?:Property)?\s*:\s*["\'][^"\']*(?<![-\w])all(?![-\w])[^"\']*["\']'
    r'|(?<![-\w])transition-all(?![-\w])', I)
SCALE_ZERO = re.compile(r'\bscale(?:X|Y|Z|3d)?\(\s*0+(?:\.0+)?\s*[,)]', I)
SCALE_ZERO_PROP = re.compile(r'\bscale\s*:\s*0+(?:\.0+)?(?=[\s,;}\]])', I)
LAYOUT_PROP_TRANSITION = re.compile(
    r'transition(?:-property)?\s*:\s*[^;{}"\']*\b(?:max-)?(?:width|height|margin|padding|top|left|right|bottom)\b', I)
KEYFRAMES_BLOCK = re.compile(r'@keyframes\s+[\w-]+\s*\{((?:[^{}]|\{[^{}]*\})*)\}', I)
LAYOUT_PROP_DECL = re.compile(r'\b(?:top|left|right|bottom|width|height|margin|padding)\s*:', I)
CSS_MOTION_DECL = re.compile(r'\b(?:transition|animation)(?:-duration)?\s*:[^;{}]*', I)
CSS_DURATION = re.compile(r'(\d+(?:\.\d+)?)\s*(ms|s)\b', I)
JS_DURATION = re.compile(r'\bduration\s*:\s*(\d+(?:\.\d+)?)(?![\w.])', I)
TW_DURATION = re.compile(r'\bduration-(\d{3,5})\b')
MOTION_CTX = re.compile(r'\b(?:transition|animat\w*|spring|variants|keyframes)\b|motion\.', I)
LINEAR_EASING = re.compile(
    r'(?:transition|animation)(?:-timing-function)?\s*:[^;{}]*\blinear\b'
    r'|["\']linear["\']', I)
HIGH_FREQ_TRIGGER = re.compile(r'\b(?:transition|animat\w*)\b\s*:|motion\.\w+', I)
INFINITE_LOOP = re.compile(
    r'animation(?:-iteration-count)?\s*:[^;{}]*\binfinite\b'
    r'|iterationCount\s*:\s*(?:Infinity|["\']infinite["\'])'
    r'|repeat\s*:\s*Infinity', I)
FRAMER_SHORTHAND = re.compile(
    r'\b(?:animate|initial|exit|whileHover|whileTap|whileInView)=\{\{[^}]*\b[xy]\s*:', I)
HAS_MOTION = re.compile(
    r'\btransition\b|\banimation\b|@keyframes|\banimate\b|useSpring|motion\.|element\.animate\(', I)
REDUCED_MOTION = re.compile(r'prefers-reduced-motion|useReducedMotion', I)

STRIP = [re.compile(r'/\*.*?\*/', re.S), re.compile(r'<!--.*?-->', re.S),
         re.compile(r'(?<![:"\'\w(,/])//[^\n]*')]


class Finding:
    """One rule violation, carrying the evidence that proves it."""

    def __init__(self, rule: str, message: str, evidence: str,
                 path: str, line: int, blocking: Optional[bool] = None) -> None:
        self.rule = rule
        self.message = message
        self.evidence = evidence
        self.path = path
        self.line = line
        # BLOCKING_RULES is the list; duration-ceiling is the one rule whose
        # blocking depends on the measured value, so it passes its own answer.
        self.blocking = rule in BLOCKING_RULES if blocking is None else blocking


def load_rules(path: Path) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def strip_comments(text: str) -> str:
    for rx in STRIP:
        text = rx.sub(lambda m: re.sub(r'[^\n]', ' ', m.group(0)), text)
    return text


def line_of(text: str, pos: int) -> int:
    return text.count("\n", 0, pos) + 1


def context_window(text: str, pos: int) -> str:
    """Text from the enclosing block's own start up to pos, so a keyword in one
    CSS rule (or JS statement) never bleeds into the next one's context."""
    before = text[:pos]
    brace = before.rfind("{")
    if brace == -1:
        return before[-CONTEXT_BEFORE:].lower()
    prev_close = before.rfind("}", 0, brace)
    start = prev_close + 1 if prev_close != -1 else max(0, brace - CONTEXT_BEFORE)
    return text[start:pos].lower()


def has_any(window: str, keywords: list) -> bool:
    return any(kw in window for kw in keywords)


def collect_files(paths: list, changed_path: Optional[str]) -> list:
    if changed_path:
        with open(changed_path, encoding="utf-8") as f:
            names = [ln.strip() for ln in f if ln.strip()]
        return [Path(n) for n in names if Path(n).suffix in UI_EXT and Path(n).is_file()]
    files = []
    for p in paths:
        path = Path(p)
        if path.is_dir():
            for f in sorted(path.rglob("*")):
                if f.is_file() and f.suffix in UI_EXT and not (set(f.parts) & SKIP_DIRS):
                    files.append(f)
        elif path.is_file():
            files.append(path)
        else:
            raise FileNotFoundError(f"no such path: {p}")
    return files


def scan_simple(rule: str, rx: re.Pattern, why: str, path: str,
                 raw: str, text: str) -> Iterator[Finding]:
    for m in rx.finditer(text):
        ln = line_of(text, m.start())
        evidence = raw.splitlines()[ln - 1].strip() if ln <= len(raw.splitlines()) else m.group(0)
        yield Finding(rule, why, evidence, path, ln)


def scan_layout_prop(path: str, raw: str, text: str) -> Iterator[Finding]:
    lines = raw.splitlines()
    for m in LAYOUT_PROP_TRANSITION.finditer(text):
        ln = line_of(text, m.start())
        why = "transition on a layout property triggers layout and paint; animate transform/opacity instead"
        yield Finding("layout-prop", why, lines[ln - 1].strip() if ln <= len(lines) else m.group(0),
                       path, ln)
    for kf in KEYFRAMES_BLOCK.finditer(text):
        block = kf.group(1)
        offset = kf.start(1)
        for m in LAYOUT_PROP_DECL.finditer(block):
            ln = line_of(text, offset + m.start())
            why = "@keyframes animates a layout property; animate transform/opacity instead"
            yield Finding("layout-prop", why, lines[ln - 1].strip() if ln <= len(lines) else m.group(0),
                           path, ln)


def scan_duration_ceiling(path: str, raw: str, text: str, cfg: dict) -> Iterator[Finding]:
    lines = raw.splitlines()
    for decl in CSS_MOTION_DECL.finditer(text):
        for val, unit in CSS_DURATION.findall(decl.group(0)):
            ms = float(val) * (1000 if unit.lower() == "s" else 1)
            yield from _ceiling_finding(path, raw, text, decl.start(), ms, cfg, lines)
    for m in JS_DURATION.finditer(text):
        near = text[max(0, m.start() - 160):m.end() + 40]
        if not MOTION_CTX.search(near):
            continue
        v = float(m.group(1))
        ms = v * 1000 if v <= 30 else v
        yield from _ceiling_finding(path, raw, text, m.start(), ms, cfg, lines)
    for m in TW_DURATION.finditer(text):
        ms = float(m.group(1))
        yield from _ceiling_finding(path, raw, text, m.start(), ms, cfg, lines)


def _ceiling_finding(path: str, raw: str, text: str, pos: int, ms: float,
                      cfg: dict, lines: list) -> Iterator[Finding]:
    window = context_window(text, pos)
    exempt = (has_any(window, cfg["constant_motion_selectors"]["keywords"])
              or has_any(window, cfg["loader_selectors"]["keywords"]))
    if exempt:
        return
    ceilings = cfg["duration_ceilings_ms"]
    kinds = cfg["kind_selectors"]
    hard_max = cfg["hard_max_ms"]
    kind = next((k for k, kws in kinds.items() if k != "_why" and has_any(window, kws)), "default")
    ceiling = ceilings.get(kind, ceilings["default"])
    if ms <= ceiling:
        return
    ln = line_of(text, pos)
    blocking = ms > hard_max
    why = (f"{int(ms)}ms exceeds the {kind} ceiling of {int(ceiling)}ms"
           + (f" and the {int(hard_max)}ms hard ceiling" if blocking else ""))
    yield Finding("duration-ceiling", why, lines[ln - 1].strip() if ln <= len(lines) else "",
                  path, ln, blocking)


def scan_linear_easing(path: str, raw: str, text: str, cfg: dict) -> Iterator[Finding]:
    lines = raw.splitlines()
    allow = cfg["constant_motion_selectors"]["keywords"]
    for m in LINEAR_EASING.finditer(text):
        window = context_window(text, m.start())
        if has_any(window, allow):
            continue
        ln = line_of(text, m.start())
        why = "linear easing on movement (linear is for constant motion only: marquees, progress bars)"
        yield Finding("linear-easing", why, lines[ln - 1].strip() if ln <= len(lines) else m.group(0),
                       path, ln)


def scan_high_frequency(path: str, raw: str, text: str, cfg: dict) -> Iterator[Finding]:
    lines = raw.splitlines()
    triggers = cfg["high_frequency_selectors"]["keywords"]
    for m in HIGH_FREQ_TRIGGER.finditer(text):
        window = context_window(text, m.start())
        if not has_any(window, triggers):
            continue
        ln = line_of(text, m.start())
        why = "animation on an element triggered 100+ times a day (keyboard shortcut, palette, row hover): remove it"
        yield Finding("high-frequency-animation", why,
                       lines[ln - 1].strip() if ln <= len(lines) else m.group(0), path, ln)


def scan_infinite_loop(path: str, raw: str, text: str, cfg: dict) -> Iterator[Finding]:
    lines = raw.splitlines()
    allow = cfg["loader_selectors"]["keywords"]
    for m in INFINITE_LOOP.finditer(text):
        window = context_window(text, m.start())
        if has_any(window, allow):
            continue
        ln = line_of(text, m.start())
        why = "infinite animation outside a loading indicator"
        yield Finding("infinite-loop", why, lines[ln - 1].strip() if ln <= len(lines) else m.group(0),
                       path, ln)


def scan_reduced_motion(files_text: dict) -> Iterator[Finding]:
    motion_seen = any(HAS_MOTION.search(t) for t in files_text.values())
    reduced_seen = any(REDUCED_MOTION.search(t) for t in files_text.values())
    if motion_seen and not reduced_seen:
        why = "motion exists in the scanned set but prefers-reduced-motion appears nowhere"
        yield Finding("no-reduced-motion", why, "", "(scanned set)", 0)


def scan_file(path: Path, cfg: dict) -> list:
    raw = path.read_text(encoding="utf-8", errors="replace")
    text = strip_comments(raw)
    p = str(path)
    findings = []
    findings += list(scan_simple("ease-in", EASE_IN, RULE_TITLES["ease-in"], p, raw, text))
    findings += list(scan_simple("transition-all", TRANSITION_ALL, RULE_TITLES["transition-all"],
                                  p, raw, text))
    findings += list(scan_simple("scale-zero", SCALE_ZERO, RULE_TITLES["scale-zero"], p, raw, text))
    findings += list(scan_simple("scale-zero-prop", SCALE_ZERO_PROP, RULE_TITLES["scale-zero-prop"],
                                  p, raw, text))
    findings += list(scan_layout_prop(p, raw, text))
    findings += list(scan_duration_ceiling(p, raw, text, cfg))
    findings += list(scan_linear_easing(p, raw, text, cfg))
    findings += list(scan_high_frequency(p, raw, text, cfg))
    findings += list(scan_infinite_loop(p, raw, text, cfg))
    findings += list(scan_simple("framer-shorthand", FRAMER_SHORTHAND, RULE_TITLES["framer-shorthand"],
                                  p, raw, text))
    return findings


def dedupe(findings: list) -> list:
    """Collapse findings that share rule + location + message (e.g. two
    comma-separated properties in one declaration hitting the same duration)."""
    seen = set()
    unique = []
    for f in findings:
        key = (f.rule, f.path, f.line, f.message)
        if key not in seen:
            seen.add(key)
            unique.append(f)
    return unique


def run_scan(files: list, cfg: dict) -> list:
    all_findings = []
    files_text = {}
    for path in files:
        raw = path.read_text(encoding="utf-8", errors="replace")
        files_text[str(path)] = strip_comments(raw)
        all_findings += scan_file(path, cfg)
    all_findings += list(scan_reduced_motion(files_text))
    return dedupe(all_findings)


def rule_number(name: str) -> int:
    return next(n for n, rn in RULE_NAMES.items() if rn == name)


def build_report(files: list, findings: list) -> str:
    lines = ["motion-bar report", "target: " + ", ".join(str(f) for f in files)]
    by_rule = {name: [f for f in findings if f.rule == name] for name in RULE_NAMES.values()}
    for name in RULE_NAMES.values():
        rows = by_rule[name]
        if not rows:
            lines.append(f"\n{name}: PASS")
            continue
        verdict = "FAIL" if any(r.blocking for r in rows) else "WARN"
        lines.append(f"\n{name}: {verdict}")
        for f in rows:
            lines.append(f"  - [{rule_number(name)}] {f.message}")
            if f.evidence:
                lines.append(f"      found: {f.evidence}")
            at = f.path if not f.line else f"{f.path}:{f.line}"
            lines.append(f"      at:    {at}")
    blocking = sum(1 for f in findings if f.blocking)
    lines.append(f"\n{'FAIL' if findings else 'PASS'}: {len(findings)} finding(s) "
                 f"across {len(RULE_NAMES)} rules ({blocking} blocking)")
    return "\n".join(lines)


def build_json(files: list, findings: list) -> dict:
    rules = {}
    for name in RULE_NAMES.values():
        rows = [f for f in findings if f.rule == name]
        rules[name] = {
            "number": rule_number(name),
            "verdict": "PASS" if not rows else ("FAIL" if any(r.blocking for r in rows) else "WARN"),
            "findings": [{"message": r.message, "evidence": r.evidence, "file": r.path,
                          "line": r.line, "blocking": r.blocking} for r in rows],
        }
    return {"target": [str(f) for f in files], "rules": rules,
            "summary": {"findings": len(findings), "rules_checked": len(RULE_NAMES),
                        "blocking": sum(1 for f in findings if f.blocking)}}


def parse_args(argv: list) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Scan UI code for motion violations.")
    parser.add_argument("paths", nargs="*", help="files or directories to scan")
    parser.add_argument("--rules", default=str(DEFAULT_RULES_PATH), help="path to rules.json")
    parser.add_argument("--changed", help="file containing a newline list of changed paths")
    parser.add_argument("--json", action="store_true", help="emit JSON instead of the text report")
    parser.add_argument("--version", action="version", version=f"motion-bar {__version__}")
    args = parser.parse_args(argv)
    if not args.paths and not args.changed:
        parser.error("give at least one path, or use --changed")
    return args


def main(argv: Optional[list] = None) -> None:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    try:
        cfg = load_rules(Path(args.rules))
        files = collect_files(args.paths, args.changed)
    except (FileNotFoundError, json.JSONDecodeError, OSError) as e:
        print(f"motion-bar: {e}", file=sys.stderr)
        sys.exit(2)
    findings = run_scan(files, cfg)
    if args.json:
        print(json.dumps(build_json(files, findings), indent=2))
    else:
        print(build_report(files, findings))
    sys.exit(1 if findings else 0)
