# Changelog

All notable changes to this project are documented in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## Unreleased

### Added

- Installable with pipx or pip from the repository, giving a `motion-bar`
  command that carries its default rules with it.
- `--version` prints the version and exits 0.

### Fixed

- Which rules block is now decided in one place, so the report and the
  documented list cannot drift apart. The README names the blocking rules.
- A scanned file is read from disk once instead of twice, halving the reads
  a scan makes.

### Changed

- `motion_bar.py` and `config/rules.json` are now the package `motion_bar/`,
  with the default rules at `motion_bar/rules.json`, so the rules travel with
  the code instead of only with a checkout. The command is
  `python3 -m motion_bar` in a clone.

## [1.0.0](https://github.com/eliferres/motion-bar/releases/tag/v1.0.0) - 2026-09-03

First public release.
