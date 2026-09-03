# Contributing

Welcome things:

- New rules, if the violation is measurable from CSS/HTML/JS source and
  every threshold lives in config/rules.json rather than the code.
- Parser fixes: real-world markup or scripts that a rule reads wrong.
- Fixes to anything the README claims that turns out not to be true.
- Selector lists tuned for a framework (Vue, Svelte, a specific design
  system), as an edited rules.json with a line saying what was measured.

Ground rules: `motion_bar.py` stays stdlib-only and single-file, every
rule ships a fixture pair (one file that trips it, one that clears it),
and the assertion is on the exact string the report gives back. Keep
`python3 -m unittest discover -s tests` green. Taste arguments belong in
an issue about a number in config/rules.json, not in the checker.
