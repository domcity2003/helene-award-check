import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from awards import load_awards
from build_walkthrough import ROOT, build
from check import DATA
from investigate import investigate
from snapshots import capture, compare


class SnapshotTests(unittest.TestCase):
    def test_capture_validates_before_publish_and_refuses_replacement(self):
        source = DATA / "openfema"
        manifest = json.loads((source / "acquisition.json").read_text(encoding="utf-8"))
        pages = {page["url"]: (source / page["filename"]).read_bytes() for page in manifest["files"]}
        incomplete = dict(pages)
        last = manifest["files"][-1]["url"]
        incomplete[last] = incomplete[last][:-20]
        with TemporaryDirectory() as temp:
            destination = Path(temp) / "sample"
            with self.assertRaises(ValueError):
                capture(destination, incomplete.__getitem__)
            self.assertFalse(destination.exists())
            self.assertEqual(capture(destination, pages.__getitem__), 3384)
            before = (destination / "acquisition.json").read_bytes()
            with self.assertRaisesRegex(ValueError, "already exists"):
                capture(destination, pages.__getitem__)
            self.assertEqual((destination / "acquisition.json").read_bytes(), before)

    def test_replay_counts_repeated_events_and_ignores_rotated_ids(self):
        common = {"worksheet": 42, "applicant_id": "NC", "category_code": "A", "version": 1}
        first = {**common, "id": "first", "date": "2026-03-31", "amount_cents": 2000}
        repeated = {**first, "id": "second"}
        revision = {**first, "id": "revised", "amount_cents": -500}
        after = {**first, "id": "new", "date": "2026-04-01", "amount_cents": 3000}
        changed = compare([first, repeated], [{**first, "id": "rotated"}, revision, after],
                          ("2025-12-31", "2026-03-31", "2026-06-30"))
        self.assertEqual(changed["added_activities"], 2)
        self.assertEqual(changed["removed_activities"], 1)
        self.assertEqual([row["total_delta_cents"] for row in changed["cutoffs"]], [0, -2500, 500])
        march = changed["cutoffs"][1]["worksheet_changes"][0]
        self.assertEqual((march["previous_cents"], march["latest_cents"]), (4000, 1500))
        self.assertEqual([row["change"] for row in march["events"]], ["removed", "added"])


class EvidenceTests(unittest.TestCase):
    def test_investigation_preserves_the_unresolved_residual(self):
        records, _ = load_awards(DATA / "openfema")
        result = investigate(records)
        self.assertEqual(result["status"], "unresolved")
        self.assertEqual(result["published_less_rebuilt_cents"], 406470134)
        self.assertEqual(result["week_after_cutoff_net_cents"], 13421998)
        self.assertEqual(result["remaining_gap_at_publication_cents"], 195558926)
        self.assertEqual(result["matching_cutoffs_through_publication"], [])

    def test_committed_offline_walkthrough_matches_the_verified_data(self):
        self.assertEqual((ROOT / "walkthrough.html").read_text(encoding="utf-8"), build())
