# Changelog

## Unreleased

### Added

- Installable with pipx or pip from the repository, giving a `motion-bar`
  command that carries its default rules with it.
- `--version` prints the version and exits 0.
- A `motion-bar-allow: <rule> <reason>` comment silences one rule on its own
  line. Allowed findings are listed with their reasons, counted on the closing
  line, and carried in `--json` under `allowed` and `summary.allowed`. A
  comment naming an unknown rule or giving no reason prints a one-line hint.

### Fixed

- Which rules block is now decided in one place, so the report and the
  documented list cannot drift apart. The README names the blocking rules.
- A scanned file is read from disk once instead of twice, halving the reads
  a scan makes.
- The demo transcript and the terminal picture now hold the full output of a
  real run, and a test replays the commands to keep them that way.
- The build's demo step now requires the failing scan to exit 1 exactly, so a
  mistyped path can no longer pass the step by exiting 2.
- The walkthrough opens with a scan of a single file, so the picture shows one
  whole run, verdict line included, instead of a report cut off part way.
- The demo picture no longer cuts its long lines off at the right edge: rows
  wider than the box ran past it mid-word with no ellipsis. Only the drawing
  changed; the recorded session is untouched.

### Changed

- `motion_bar.py` and `config/rules.json` are now the package `motion_bar/`,
  with the default rules at `motion_bar/rules.json`, so the rules travel with
  the code instead of only with a checkout. The command is
  `python3 -m motion_bar` in a clone.

## [1.0.0](https://github.com/eliferres/motion-bar/releases/tag/v1.0.0) - 2026-09-03

First public release.
