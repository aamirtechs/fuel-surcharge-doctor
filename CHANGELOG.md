# Changelog

## 1.0.0 - 2026-11-03

Initial release.

* Per-mile fuel surcharge: (diesel - base) / MPG x miles, with an
  optional per-mile floor.
* Percent method: linehaul x percent / 100.
* Audit mode: compares computed FSC with billed FSC per load and
  flags UNDERPAID, OVERPAID, or OK within a tolerance.
* Summary totals: miles, total FSC, total due, audit counts, and
  total underpaid amount.
* Text and JSON reports, `--check` CI gate, `--out` file output.
* Zero dependencies, Python 3.9 or newer.
