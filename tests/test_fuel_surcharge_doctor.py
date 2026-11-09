"""Tests for fuel-surcharge-doctor. Run: python3 -m unittest discover -s tests -v"""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from decimal import Decimal

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import fuel_surcharge_doctor as fsc

CONTRACT = {
    "method": "per_mile", "base_price": Decimal("1.20"), "mpg": Decimal("6.0"),
    "floor": Decimal("0"), "tolerance": Decimal("0.01"),
    "diesel_price": Decimal("3.90"), "percent": None,
}


def run_cli(args, cwd=None):
    script = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                          "fuel_surcharge_doctor.py")
    return subprocess.run([sys.executable, script] + args, capture_output=True,
                          text=True, cwd=cwd)


def write_json(directory, name, data):
    path = os.path.join(directory, name)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(data, handle)
    return path


class TestPerMile(unittest.TestCase):
    def test_textbook_example(self):
        # (3.90 - 1.25) / 6.0 = 0.4417 per mile; 850 miles = 375.45
        contract = dict(CONTRACT, base_price=Decimal("1.25"))
        result = fsc.compute_load(
            {"load_id": "LD-1", "miles": 850, "diesel_price": 3.90}, contract)
        self.assertEqual(result["fsc_per_mile"], "0.44")
        self.assertEqual(result["fsc"], "375.42")

    def test_zero_when_diesel_below_base(self):
        result = fsc.compute_load(
            {"load_id": "LD-2", "miles": 500, "diesel_price": 1.10}, CONTRACT)
        self.assertEqual(result["fsc"], "0.00")

    def test_floor_applies(self):
        contract = dict(CONTRACT, floor=Decimal("0.10"))
        result = fsc.compute_load(
            {"load_id": "LD-3", "miles": 100, "diesel_price": 1.10}, contract)
        self.assertEqual(result["fsc"], "10.00")

    def test_zero_miles(self):
        result = fsc.compute_load(
            {"load_id": "LD-4", "miles": 0, "diesel_price": 3.90}, CONTRACT)
        self.assertEqual(result["fsc"], "0.00")

    def test_negative_miles_rejected(self):
        with self.assertRaises(ValueError):
            fsc.compute_load({"load_id": "LD-5", "miles": -10, "diesel_price": 3.90}, CONTRACT)

    def test_zero_mpg_rejected(self):
        contract = dict(CONTRACT, mpg=Decimal("0"))
        with self.assertRaises(ValueError):
            fsc.compute_load({"load_id": "LD-6", "miles": 100, "diesel_price": 3.90}, contract)

    def test_per_load_overrides_contract(self):
        result = fsc.compute_load(
            {"load_id": "LD-7", "miles": 500, "diesel_price": 4.20,
             "base_price": 1.20, "mpg": 6.5}, CONTRACT)
        # (4.20 - 1.20) / 6.5 = 0.461538... per mile, * 500 = 230.77
        self.assertEqual(result["fsc"], "230.77")

    def test_total_due_when_linehaul_present(self):
        result = fsc.compute_load(
            {"load_id": "LD-8", "miles": 500, "diesel_price": 3.60, "linehaul": 2000},
            CONTRACT)
        # (3.60 - 1.20) / 6 = 0.40 per mile, * 500 = 200.00
        self.assertEqual(result["fsc"], "200.00")
        self.assertEqual(result["total_due"], "2200.00")


class TestPercentMethod(unittest.TestCase):
    def test_percent_of_linehaul(self):
        contract = dict(CONTRACT, method="percent", percent=Decimal("25"))
        result = fsc.compute_load(
            {"load_id": "LD-9", "miles": 500, "linehaul": 2000, "diesel_price": 3.80},
            contract)
        self.assertEqual(result["fsc"], "500.00")

    def test_percent_needs_linehaul(self):
        contract = dict(CONTRACT, method="percent", percent=Decimal("25"))
        with self.assertRaises(ValueError):
            fsc.compute_load({"load_id": "LD-10", "miles": 500, "diesel_price": 3.80},
                             contract)

    def test_unknown_method_rejected(self):
        with self.assertRaises(ValueError):
            fsc.compute_load({"load_id": "LD-11", "miles": 100, "diesel_price": 3.80,
                              "method": "mystery"}, CONTRACT)


class TestAudit(unittest.TestCase):
    def test_underpaid_flagged(self):
        result = fsc.compute_load(
            {"load_id": "LD-12", "miles": 500, "diesel_price": 3.60, "billed_fsc": 150},
            CONTRACT)
        self.assertEqual(result["fsc"], "200.00")
        self.assertEqual(result["audit"], "UNDERPAID")
        self.assertEqual(result["difference"], "50.00")

    def test_overpaid_flagged(self):
        result = fsc.compute_load(
            {"load_id": "LD-13", "miles": 500, "diesel_price": 3.60, "billed_fsc": 250},
            CONTRACT)
        self.assertEqual(result["audit"], "OVERPAID")

    def test_within_tolerance_is_ok(self):
        result = fsc.compute_load(
            {"load_id": "LD-14", "miles": 500, "diesel_price": 3.60, "billed_fsc": 200.01},
            CONTRACT)
        self.assertEqual(result["audit"], "OK")

    def test_summary_counts(self):
        results = [
            fsc.compute_load({"load_id": "A", "miles": 500, "diesel_price": 3.60,
                              "billed_fsc": 150}, CONTRACT),
            fsc.compute_load({"load_id": "B", "miles": 500, "diesel_price": 3.60,
                              "billed_fsc": 200}, CONTRACT),
        ]
        summary = fsc.summarize(results)
        self.assertEqual(summary["underpaid"], 1)
        self.assertEqual(summary["ok"], 1)
        self.assertEqual(summary["underpaid_amount"], "50.00")
        self.assertEqual(summary["total_fsc"], "400.00")


class TestCli(unittest.TestCase):
    def test_text_report_and_check_exit_codes(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = write_json(tmp, "loads.json", [
                {"load_id": "LD-101", "miles": 850, "linehaul": 2125,
                 "diesel_price": 3.90, "billed_fsc": 350},
                {"load_id": "LD-102", "miles": 500, "linehaul": 2000,
                 "diesel_price": 3.60, "billed_fsc": 200},
            ])
            proc = run_cli([path, "--base", "1.20", "--mpg", "6.0"])
            self.assertEqual(proc.returncode, 0)
            self.assertIn("LD-101", proc.stdout)
            self.assertIn("UNDERPAID", proc.stdout)
            proc = run_cli([path, "--base", "1.20", "--mpg", "6.0", "--check"])
            self.assertEqual(proc.returncode, 1)
            proc = run_cli([path, "--base", "1.20", "--mpg", "6.0", "--json"])
            data = json.loads(proc.stdout)
            self.assertEqual(data["summary"]["loads"], 2)
            self.assertEqual(data["summary"]["underpaid"], 1)

    def test_check_passes_when_all_ok(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = write_json(tmp, "loads.json", [
                {"load_id": "LD-201", "miles": 500, "diesel_price": 3.60,
                 "billed_fsc": 200},
            ])
            proc = run_cli([path, "--check"])
            self.assertEqual(proc.returncode, 0)

    def test_missing_file_is_error(self):
        proc = run_cli(["/nonexistent/loads.json"])
        self.assertEqual(proc.returncode, 2)
        self.assertIn("error", proc.stderr)

    def test_bad_json_is_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "bad.json")
            with open(path, "w", encoding="utf-8") as handle:
                handle.write("{not json")
            proc = run_cli([path])
            self.assertEqual(proc.returncode, 2)

    def test_object_wrapper_input(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = write_json(tmp, "loads.json",
                              {"loads": [{"load_id": "LD-301", "miles": 100,
                                         "diesel_price": 3.00}]})
            proc = run_cli([path, "--diesel", "3.00"])
            self.assertEqual(proc.returncode, 0)
            self.assertIn("LD-301", proc.stdout)

    def test_out_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = write_json(tmp, "loads.json",
                             [{"load_id": "LD-401", "miles": 100, "diesel_price": 3.00}])
            out = os.path.join(tmp, "report.txt")
            proc = run_cli([src, "--out", out])
            self.assertEqual(proc.returncode, 0)
            self.assertEqual(proc.stdout, "")
            with open(out, encoding="utf-8") as handle:
                self.assertIn("LD-401", handle.read())


if __name__ == "__main__":
    unittest.main()
