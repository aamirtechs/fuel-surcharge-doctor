#!/usr/bin/env python3
"""fuel-surcharge-doctor: audit fuel surcharges on a batch of loads.

A zero-dependency CLI for dispatchers, owner-operators, and small
carriers. It computes the fuel surcharge (FSC) for each load under a
contract and, in audit mode, compares it with the amount actually
billed, so underpaid surcharges stop slipping through quietly.

Two contract methods are supported:

* per_mile (the usual truckload method):
  FSC per mile = max(diesel_price - base_price, 0) / mpg,
  unless a floor applies, and FSC = FSC per mile * miles.
  When diesel is at or below the base price, the surcharge is zero
  unless the contract sets a minimum (floor) per-mile rate.
* percent (the usual LTL / percentage-table method):
  FSC = linehaul * percent / 100, where percent comes from the
  contract table for the current diesel price, or from --percent.

All money math uses Decimal and rounds half up to cents.

Input is a JSON list, or an object with a "loads" list. Each load
needs "miles". Per-load fields override the contract defaults:

    {"load_id": "LD-101", "miles": 850, "linehaul": 2125.00,
     "diesel_price": 3.90, "billed_fsc": 350.00}

Contract defaults come from flags: --base, --mpg, --method,
--percent, --floor, and --tolerance (audit slack in dollars).
"""

import argparse
import json
import sys
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation

CENT = Decimal("0.01")
ZERO = Decimal("0")


def to_decimal(value, field):
    """Convert a JSON number or numeric string to Decimal, or raise."""
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise ValueError("field %r must be a number, got %r" % (field, value))
    if result.is_nan() or result.is_infinite():
        raise ValueError("field %r must be a finite number" % field)
    return result


def money(value):
    """Round a Decimal to cents, half up."""
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def fmt(value):
    """Format a Decimal as dollars with two decimals."""
    return "$%s" % money(value)


def load_records(path):
    """Read the loads JSON file and return a list of dicts."""
    with open(path, "r", encoding="utf-8") as handle:
        data = json.load(handle)
    if isinstance(data, dict):
        data = data.get("loads")
    if not isinstance(data, list):
        raise ValueError("input must be a JSON list or an object with a 'loads' list")
    for index, record in enumerate(data):
        if not isinstance(record, dict):
            raise ValueError("load at index %d is not an object" % index)
    return data


def compute_load(record, contract):
    """Compute the surcharge for one load. Returns a result dict."""
    label = record.get("load_id") or record.get("id") or "?"
    if "miles" not in record:
        raise ValueError("load %s is missing 'miles'" % label)
    miles = to_decimal(record["miles"], "miles")
    if miles < 0:
        raise ValueError("load %s has negative miles" % label)
    method = record.get("method", contract["method"])
    diesel = to_decimal(record.get("diesel_price", contract["diesel_price"]), "diesel_price")
    base = to_decimal(record.get("base_price", contract["base_price"]), "base_price")
    if method == "per_mile":
        mpg = to_decimal(record.get("mpg", contract["mpg"]), "mpg")
        if mpg <= 0:
            raise ValueError("load %s needs mpg greater than 0" % label)
        floor = to_decimal(record.get("floor", contract["floor"]), "floor")
        spread = diesel - base
        per_mile = spread / mpg if spread > 0 else ZERO
        if per_mile < floor:
            per_mile = floor
        fsc = money(per_mile * miles)
        detail = {
            "method": "per_mile",
            "diesel_price": str(diesel),
            "base_price": str(base),
            "mpg": str(mpg),
            "fsc_per_mile": str(money(per_mile)),
        }
    elif method == "percent":
        if "linehaul" not in record:
            raise ValueError("load %s needs 'linehaul' for percent method" % label)
        linehaul = to_decimal(record["linehaul"], "linehaul")
        if linehaul < 0:
            raise ValueError("load %s has negative linehaul" % label)
        percent = to_decimal(record.get("percent", contract["percent"]), "percent")
        if percent < 0:
            raise ValueError("load %s has negative percent" % label)
        fsc = money(linehaul * percent / Decimal("100"))
        detail = {
            "method": "percent",
            "diesel_price": str(diesel),
            "base_price": str(base),
            "percent": str(percent),
            "linehaul": str(money(linehaul)),
        }
    else:
        raise ValueError("load %s has unknown method %r" % (label, method))
    result = {"load_id": str(label), "miles": str(miles), "fsc": str(fsc)}
    result.update(detail)
    if "linehaul" in record:
        linehaul = to_decimal(record["linehaul"], "linehaul")
        result["linehaul"] = str(money(linehaul))
        result["total_due"] = str(money(linehaul + fsc))
    if "billed_fsc" in record and record["billed_fsc"] is not None:
        billed = to_decimal(record["billed_fsc"], "billed_fsc")
        result["billed_fsc"] = str(money(billed))
        diff = money(fsc - billed)
        result["difference"] = str(diff)
        if diff > contract["tolerance"]:
            result["audit"] = "UNDERPAID"
        elif diff < -contract["tolerance"]:
            result["audit"] = "OVERPAID"
        else:
            result["audit"] = "OK"
    return result


def summarize(results):
    """Aggregate totals and audit counts across computed loads."""
    total_fsc = sum((Decimal(r["fsc"]) for r in results), ZERO)
    total_miles = sum((Decimal(r["miles"]) for r in results), ZERO)
    summary = {
        "loads": len(results),
        "total_miles": str(total_miles),
        "total_fsc": str(money(total_fsc)),
    }
    if results and all("total_due" in r for r in results):
        summary["total_due"] = str(money(sum(Decimal(r["total_due"]) for r in results)))
    audited = [r for r in results if "audit" in r]
    if audited:
        summary["audited"] = len(audited)
        summary["underpaid"] = sum(1 for r in audited if r["audit"] == "UNDERPAID")
        summary["overpaid"] = sum(1 for r in audited if r["audit"] == "OVERPAID")
        summary["ok"] = sum(1 for r in audited if r["audit"] == "OK")
        summary["underpaid_amount"] = str(money(sum(
            (Decimal(r["difference"]) for r in audited if r["audit"] == "UNDERPAID"),
            ZERO)))
    return summary


def render_text(results, summary):
    """Render the human readable report."""
    lines = []
    for result in results:
        if result["method"] == "per_mile":
            lines.append(
                "%s: %s miles at %s/mile (diesel %s, base %s, %s mpg) -> FSC %s"
                % (result["load_id"], result["miles"], fmt(Decimal(result["fsc_per_mile"])),
                   result["diesel_price"], result["base_price"], result["mpg"],
                   fmt(Decimal(result["fsc"]))))
        else:
            lines.append(
                "%s: %s miles, linehaul %s at %s%% -> FSC %s"
                % (result["load_id"], result["miles"], fmt(Decimal(result["linehaul"])),
                   result["percent"], fmt(Decimal(result["fsc"]))))
        if "audit" in result:
            lines.append(
                "    billed %s, difference %s (%s)"
                % (fmt(Decimal(result["billed_fsc"])), fmt(Decimal(result["difference"])),
                   result["audit"]))
        elif "total_due" in result:
            lines.append("    total due (linehaul + FSC): %s" % fmt(Decimal(result["total_due"])))
    lines.append("")
    lines.append("Loads: %d, miles: %s, total FSC: %s"
                 % (summary["loads"], summary["total_miles"], fmt(Decimal(summary["total_fsc"]))))
    if "total_due" in summary:
        lines.append("Total due: %s" % fmt(Decimal(summary["total_due"])))
    if "audited" in summary:
        lines.append("Audited: %d, underpaid: %d (%s), overpaid: %d, ok: %d"
                     % (summary["audited"], summary["underpaid"],
                        fmt(Decimal(summary["underpaid_amount"])),
                        summary["overpaid"], summary["ok"]))
    return "\n".join(lines) + "\n"


def build_parser():
    parser = argparse.ArgumentParser(
        prog="fuel-surcharge-doctor",
        description="Compute and audit fuel surcharges for a batch of loads.")
    parser.add_argument("input", help="JSON file with loads")
    parser.add_argument("--base", default="1.20",
                        help="contract base fuel price per gallon (default 1.20)")
    parser.add_argument("--mpg", default="6.0",
                        help="contract fleet MPG for per_mile method (default 6.0)")
    parser.add_argument("--diesel", default=None,
                        help="current diesel price per gallon (default: per-load value)")
    parser.add_argument("--method", choices=["per_mile", "percent"], default="per_mile",
                        help="contract method (default per_mile)")
    parser.add_argument("--percent", default=None,
                        help="surcharge percent for percent method")
    parser.add_argument("--floor", default="0",
                        help="minimum per-mile surcharge (default 0)")
    parser.add_argument("--tolerance", default="0.01",
                        help="audit slack in dollars (default 0.01)")
    parser.add_argument("--json", action="store_true", help="emit JSON instead of text")
    parser.add_argument("--check", action="store_true",
                        help="exit 1 if any audited load is underpaid or overpaid")
    parser.add_argument("--out", default=None, help="write the report to this file")
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        contract = {
            "method": args.method,
            "base_price": to_decimal(args.base, "base"),
            "mpg": to_decimal(args.mpg, "mpg"),
            "floor": to_decimal(args.floor, "floor"),
            "tolerance": to_decimal(args.tolerance, "tolerance"),
            "diesel_price": to_decimal(args.diesel, "diesel") if args.diesel is not None else None,
            "percent": to_decimal(args.percent, "percent") if args.percent is not None else None,
        }
        if contract["mpg"] <= 0:
            raise ValueError("mpg must be greater than 0")
        if contract["method"] == "per_mile" and contract["diesel_price"] is None:
            pass  # per-load diesel_price required then, checked per load
        records = load_records(args.input)
        results = []
        for record in records:
            merged = dict(record)
            if contract["diesel_price"] is not None:
                merged.setdefault("diesel_price", str(contract["diesel_price"]))
            if contract["method"] == "percent" and contract["percent"] is not None:
                merged.setdefault("percent", str(contract["percent"]))
            if "diesel_price" not in merged:
                raise ValueError("load %s is missing 'diesel_price' (pass --diesel)"
                                 % (merged.get("load_id") or merged.get("id") or "?"))
            results.append(compute_load(merged, contract))
    except (ValueError, OSError, json.JSONDecodeError) as exc:
        print("error: %s" % exc, file=sys.stderr)
        return 2
    summary = summarize(results)
    if args.json:
        output = json.dumps({"loads": results, "summary": summary}, indent=2) + "\n"
    else:
        output = render_text(results, summary)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as handle:
            handle.write(output)
    else:
        sys.stdout.write(output)
    if args.check and any(r.get("audit") in ("UNDERPAID", "OVERPAID") for r in results):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
