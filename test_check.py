import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from check import DATA, coverage, load_awards, reconcile, review


ROOT = Path(__file__).resolve().parent
MARCH = "2026-03-31"


def cli(*args):
    return subprocess.run(
        [sys.executable, str(ROOT / "check.py"), *map(str, args)],
        cwd=ROOT, capture_output=True, text=True, check=False,
    )


class BriefingChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.records, _ = load_awards(DATA / "openfema")

    def test_all_published_category_balances(self):
        result = reconcile(self.records, DATA)
        self.assertEqual(len(self.records), 3384)
        self.assertEqual([len(row["category_cents"]) for row in result], [8, 8, 8])
        self.assertEqual([row["total_cents"] for row in result], [78400049100, 98363953991, 153024720835])
        self.assertEqual(coverage(self.records, MARCH), {
            "worksheets_at_cutoff": 2339,
            "worksheets_with_later_balance_change": 131,
            "worksheets_first_seen_after_cutoff": 762,
        })

    def test_demo_evidence_and_corrected_draft(self):
        draft = cli("review", "examples/march-draft.csv", "--as-of", MARCH, "--json")
        self.assertEqual(draft.returncode, 1, draft.stderr)
        data = json.loads(draft.stdout)
        self.assertEqual(len(data["source_pages"]), 4)
        ncem, madison, category, total = data["results"]
        self.assertEqual(ncem["status"], "matches_later_balance")
        self.assertEqual(ncem["supported_cents"], 20001345945)
        self.assertEqual(ncem["difference_cents"], 8633174757)
        self.assertEqual([(row["date"], row["amount_cents"]) for row in ncem["after_cutoff"]], [
            ("2026-04-23", 8000022817), ("2026-10-21", 633151940),
        ])
        self.assertEqual(madison["supported_cents"], 86070303)
        self.assertEqual([row["amount_cents"] for row in madison["through_cutoff"]], [163669733, -77599430])
        self.assertEqual([row["status"] for row in (madison, category, total)], ["match"] * 3)
        corrected = cli("review", "examples/march-reviewed.csv", "--as-of", MARCH)
        self.assertEqual(corrected.returncode, 0, corrected.stderr)
        self.assertIn("4/4 match", corrected.stdout)

    def test_missing_future_and_real_mismatch(self):
        lines = [
            ("unknown", "worksheet", 9999999999, 0),
            ("future", "worksheet", 4789, 0),
            ("penny", "worksheet", 370, 86070304),
        ]
        unknown, future, penny = review(self.records, lines, MARCH)
        self.assertEqual(unknown["status"], "unknown_worksheet")
        self.assertIsNone(unknown["supported_cents"])
        self.assertFalse(unknown["after_cutoff"])
        self.assertEqual(future["status"], "no_activity_by_cutoff")
        self.assertIsNone(future["supported_cents"])
        self.assertTrue(future["after_cutoff"])
        self.assertEqual(penny["status"], "mismatch")
        self.assertEqual(penny["difference_cents"], 1)

    def test_rejects_malformed_input_without_partial_results(self):
        header = "line_id,scope,key,proposed_usd\n"
        cases = {
            "duplicate": "same,worksheet,370,1\nsame,category,B,1",
            "fractional cent": "line,worksheet,370,1.001",
            "extra field": "line,worksheet,370,1,extra",
            "empty": "",
        }
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "draft.csv"
            for name, rows in cases.items():
                with self.subTest(name=name):
                    path.write_text(header + rows, encoding="utf-8")
                    output = cli("review", path, "--as-of", MARCH, "--json")
                    self.assertEqual(output.returncode, 2)
                    self.assertIn("Review blocked", output.stderr)
                    self.assertEqual(output.stdout, "")

    def test_source_mutation_and_published_disagreement_block_review(self):
        with tempfile.TemporaryDirectory() as temp:
            data = Path(temp) / "data"
            shutil.copytree(DATA, data)
            page = data / "openfema" / "award-3000.json"
            original = page.read_bytes()
            page.write_bytes(original + b"\n")
            output = cli("--data", data, "review", "examples/march-reviewed.csv", "--as-of", MARCH, "--json")
            self.assertEqual(output.returncode, 2)
            self.assertIn("differs from the acquisition manifest", output.stderr)
            self.assertEqual(output.stdout, "")
            page.write_bytes(original)

            reference = data / "published-balances.json"
            content = json.loads(reference.read_text(encoding="utf-8"))
            content["snapshots"][2]["amounts"]["B"] = "572529086.67"
            reference.write_text(json.dumps(content), encoding="utf-8")
            output = cli("--data", data, "reconcile", "--json")
            self.assertEqual(output.returncode, 2)
            self.assertIn("2026-03-31 category B by 0.01 USD", output.stderr)
            self.assertEqual(output.stdout, "")


if __name__ == "__main__":
    unittest.main()
