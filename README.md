# fuel-surcharge-doctor
**Live tool:** https://aamirtechs.github.io/fuel-surcharge-doctor/ (runs in your browser, no install)

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://github.com/aamirtechs/fuel-surcharge-doctor/blob/main/LICENSE) [![PRs Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg)](https://github.com/aamirtechs/fuel-surcharge-doctor/issues)

A zero-dependency Python CLI that computes fuel surcharges for a batch
of loads and audits them against what was actually billed, so an
underpaid surcharge stops slipping through quietly.

Web fuel surcharge calculators answer one load at a time. Dispatchers
audit whole weeks of rate confirmations, and that is the gap this tool
fills: one JSON file of loads, one command, and a report that names
every load that was underpaid, overpaid, or fine.

## Methods

Two contract methods, matching how real freight contracts work:

* `per_mile` (the usual truckload method):
  FSC per mile = (diesel price - base price) / MPG, floored at zero
  unless the contract sets a minimum per-mile rate.
  FSC = FSC per mile x miles.
* `percent` (the usual percentage-table method):
  FSC = linehaul x percent / 100.

All money math uses Decimal and rounds half up to cents.

## Install

Requires Python 3.9 or newer. No dependencies beyond the standard library.

```bash
pip install fuel-surcharge-doctor
```

Or run it straight from the source checkout:

```bash
python3 fuel_surcharge_doctor.py examples/loads.json
```

## Input format

A JSON list, or an object with a `loads` list. Each load needs
`miles` and `diesel_price` (or pass `--diesel` for the whole batch).
Per-load fields override the contract defaults. `billed_fsc` turns a
load into an audited load; `linehaul` adds a total due.

```json
[
  {"load_id": "LD-101", "miles": 850, "linehaul": 2125.00,
   "diesel_price": 3.90, "billed_fsc": 350.00},
  {"load_id": "LD-102", "miles": 500, "linehaul": 2000.00,
   "diesel_price": 3.60, "billed_fsc": 200.00}
]
```

## Usage

Audit a week of loads against a contract of $1.20 base price and
6.0 MPG (the defaults):

```bash
python3 fuel_surcharge_doctor.py examples/loads.json
```

Captured output:

```
LD-101: 850 miles at $0.45/mile (diesel 3.9, base 1.20, 6.0 mpg) -> FSC $382.50
    billed $350.00, difference $32.50 (UNDERPAID)
LD-102: 500 miles at $0.40/mile (diesel 3.6, base 1.20, 6.0 mpg) -> FSC $200.00
    billed $200.00, difference $0.00 (OK)
LD-103: 1200 miles at $0.50/mile (diesel 4.2, base 1.20, 6.0 mpg) -> FSC $600.00
    billed $620.00, difference $-20.00 (OVERPAID)

Loads: 3, miles: 2550, total FSC: $1182.50
Total due: $8307.50
Audited: 3, underpaid: 1 ($32.50), overpaid: 1, ok: 1
```

Use it as a CI gate: `--check` exits 1 when any audited load is
underpaid or overpaid (exit 1 on the example above, since LD-101 is
underpaid). `--json` emits the full per-load report as JSON, `--out`
writes the report to a file, and `--tolerance` sets the audit slack
in dollars (default $0.01).

A percentage contract looks like this:

```bash
python3 fuel_surcharge_doctor.py loads.json --method percent --percent 25
```

## Options

| Flag | Meaning |
| --- | --- |
| `--base` | Contract base fuel price per gallon (default 1.20) |
| `--mpg` | Contract fleet MPG for the per-mile method (default 6.0) |
| `--diesel` | Diesel price for the whole batch (overrides per-load values only when the load has none) |
| `--method` | `per_mile` or `percent` (default per_mile) |
| `--percent` | Surcharge percent for the percent method |
| `--floor` | Minimum per-mile surcharge (default 0) |
| `--tolerance` | Audit slack in dollars (default 0.01) |
| `--json` | Emit JSON instead of text |
| `--check` | Exit 1 if any audited load is underpaid or overpaid |
| `--out` | Write the report to a file |

## Tests

```bash
python3 -m unittest discover -s tests -v
```

21 tests, all passing: per-mile math, floor, zero diesel spread,
percent method, audit flags and tolerance, summary totals, and CLI
behavior including exit codes, JSON output, and file output.

## License

MIT. See [LICENSE](LICENSE).
