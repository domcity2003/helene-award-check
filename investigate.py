"""Trace the June 2025 debris-removal discrepancy to available FEMA evidence."""

import argparse
from collections import defaultdict
import json
import sys

from awards import SOURCE_BASE, SOURCE_PATH, load_awards
from check import DATA, audit_history, money


def investigate(records, data=DATA):
    cutoff = "2025-06-30"
    published_date = "2025-08-15"
    observation = next(row for row in audit_history(records, data)
                       if row["cutoff"] == cutoff and row["category"] == "A")
    rows = sorted((row for row in records if row["category_code"] == "A"),
                  key=lambda row: (row["date"], row["worksheet"], row["id"]))
    before = [row for row in rows if row["date"] <= cutoff]
    later = [row for row in rows if cutoff < row["date"] <= published_date]
    through = observation["rebuilt_cents"]
    gap = -observation["rebuilt_less_published_cents"]
    by_worksheet = defaultdict(int)
    by_date = defaultdict(int)
    for row in before:
        by_worksheet[row["worksheet"]] += row["amount_cents"]
    for row in later:
        by_date[row["date"]] += row["amount_cents"]
    running = through
    equivalent_cutoffs = []
    for day, net in sorted(by_date.items()):
        running += net
        if running == through + gap:
            equivalent_cutoffs.append(day)
    week = [row for row in later if row["date"] <= "2025-07-07"]
    return {
        "status": "unresolved" if gap else "matched",
        "observation": observation,
        "published_less_rebuilt_cents": gap,
        "activities_at_cutoff": len(before),
        "worksheets_at_cutoff": len(by_worksheet),
        "revisions_at_cutoff": sum(row["version"] > 0 for row in before),
        "negative_activities_at_cutoff": sum(row["amount_cents"] < 0 for row in before),
        "single_activity_matches": [row["id"] for row in before + later if abs(row["amount_cents"]) == abs(gap)],
        "single_worksheet_matches": [key for key, value in sorted(by_worksheet.items()) if value == gap],
        "matching_cutoffs_through_publication": equivalent_cutoffs,
        "week_after_cutoff_net_cents": sum(row["amount_cents"] for row in week),
        "publication_date": published_date,
        "replay_at_publication_cents": running,
        "remaining_gap_at_publication_cents": through + gap - running,
        "evidence_needed": "The June 30 FEMA Grants Portal Category A export used for the state report, including worksheet number, version, obligation date and federal share. Compare each row with the public award activity history.",
        "openfema_url": f"{SOURCE_BASE}{SOURCE_PATH}?%24filter=disasterNumber%20eq%204827%20and%20damageCategoryCode%20eq%20%27A%20-%20Debris%20Removal%27",
        "through_cutoff": before,
        "after_cutoff_through_publication": later,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="Include the complete worksheet and activity evidence")
    args = parser.parse_args()
    try:
        records, sources = load_awards(DATA / "openfema")
        result = investigate(records)
    except (ValueError, TypeError, OSError, KeyError, StopIteration) as exc:
        print(f"Investigation blocked: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps({**result, "source_pages": sources}, indent=2))
    else:
        print(f"June 2025 Category A | {result['status']}")
        print(f"Published: {result['observation']['published_amount']} | Rebuilt: ${money(result['observation']['rebuilt_cents'])}")
        print(f"Published less rebuilt: ${money(result['published_less_rebuilt_cents'])}")
        print(f"At cutoff: {result['activities_at_cutoff']} activities on {result['worksheets_at_cutoff']} worksheets.")
        print(f"Net activity over the next seven days: ${money(result['week_after_cutoff_net_cents'])}.")
        print(f"Gap if extended through publication: ${money(result['remaining_gap_at_publication_cents'])}.")
        print(f"Exact matches to gap: {len(result['single_activity_matches'])} single activities, "
              f"{len(result['single_worksheet_matches'])} single worksheet balances, "
              f"{len(result['matching_cutoffs_through_publication'])} later activity dates through publication.")
        print(f"Evidence needed: {result['evidence_needed']}")
    return int(result["status"] == "unresolved")


if __name__ == "__main__":
    sys.exit(main())
