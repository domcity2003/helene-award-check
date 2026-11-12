"""Capture OpenFEMA source pages and compare historical award balances."""

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from urllib.request import Request, urlopen

from awards import DATASET, PAGE_SIZE, SOURCE_BASE, SOURCE_PATH, cutoff_balance, load_awards
from check import CUTOFFS, DATA, money


def download(url):
    request = Request(url, headers={"Accept": "application/json", "User-Agent": "HeleneAwardCheck/1.0"})
    with urlopen(request, timeout=30) as response:
        return response.read()


def capture(destination, fetch=download):
    if destination.exists() or destination.is_symlink():
        raise ValueError("Capture already exists. Choose a new directory.")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(dir=destination.parent) as temp:
        staging = Path(temp) / "capture"
        staging.mkdir()
        files = []
        total = None
        offset = 0
        while total is None or offset < total:
            relative = (f"{SOURCE_PATH}?%24filter=disasterNumber%20eq%204827&%24top={PAGE_SIZE}"
                        f"&%24count=true&%24orderby=id&%24skip={offset}")
            payload = fetch(SOURCE_BASE + relative)
            page = json.loads(payload.decode("utf-8-sig"))
            metadata = page["metadata"]
            count = metadata["count"]
            if type(count) is not int or count <= 0 or (total is not None and total != count):
                raise ValueError("Unexpected or changing record count. Retry the entire capture.")
            total = count
            name = f"award-{offset}.json"
            (staging / name).write_bytes(payload)
            files.append({
                "filename": name, "url": SOURCE_BASE + relative,
                "sha256": hashlib.sha256(payload).hexdigest(), "retrieved_utc": metadata["rundate"],
                "reported_count": total, "row_count": len(page[DATASET]),
            })
            offset += PAGE_SIZE
        manifest = {"source_base": SOURCE_BASE, "captured_utc": datetime.now(timezone.utc).isoformat(), "files": files}
        (staging / "acquisition.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        records, _ = load_awards(staging)
        if destination.exists() or destination.is_symlink():
            raise ValueError("Capture already exists. Choose a new directory.")
        staging.rename(destination)
    return len(records)


EVENT_FIELDS = ("worksheet", "applicant_id", "category_code", "date", "version", "amount_cents")


def compare(previous, latest, cutoffs):
    # IDs can change across downloads. Compare financial event multiplicities.
    def events(records):
        return Counter(tuple(row[field] for field in EVENT_FIELDS) for row in records)

    old, new = events(previous), events(latest)
    removed, added = old - new, new - old
    changes = defaultdict(list)
    for direction, difference in (("removed", removed), ("added", added)):
        for event, count in sorted(difference.items()):
            worksheet, _, category, _, _, amount = event
            signed = amount * count * (-1 if direction == "removed" else 1)
            changes[worksheet, category].append({
                **dict(zip(EVENT_FIELDS, event)), "change": direction,
                "count": count, "delta_cents": signed,
            })
    results = []
    for cutoff in cutoffs:
        previous_balances, _ = cutoff_balance(previous, cutoff)
        latest_balances, _ = cutoff_balance(latest, cutoff)
        previous_worksheets = defaultdict(int)
        for row in previous:
            if row["date"] <= cutoff:
                previous_worksheets[row["worksheet"], row["category_code"]] += row["amount_cents"]
        worksheets = []
        category_delta = defaultdict(int)
        for (worksheet, category), events_changed in sorted(changes.items()):
            effective = [event for event in events_changed if event["date"] <= cutoff]
            if effective:
                delta = sum(event["delta_cents"] for event in effective)
                category_delta[category] += delta
                opening = previous_worksheets[worksheet, category]
                worksheets.append({"worksheet": worksheet, "category": category,
                                   "previous_cents": opening, "latest_cents": opening + delta,
                                   "delta_cents": delta, "events": effective})
        results.append({"cutoff": cutoff, "worksheet_changes": worksheets,
                        "category_delta_cents": dict(category_delta),
                        "previous_category_cents": previous_balances,
                        "latest_category_cents": latest_balances,
                        "previous_total_cents": sum(previous_balances.values()),
                        "latest_total_cents": sum(latest_balances.values()),
                        "total_delta_cents": sum(category_delta.values())})
    return {"added_activities": added.total(), "removed_activities": removed.total(), "cutoffs": results}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    pull = commands.add_parser("capture", help="Download and verify a new capture")
    pull.add_argument("destination", type=Path)
    diff = commands.add_parser("compare", help="Compare two verified captures")
    diff.add_argument("latest", type=Path)
    diff.add_argument("--previous", type=Path, default=DATA / "openfema")
    diff.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.command == "capture":
            count = capture(args.destination)
            print(f"Saved {count:,} verified activities in {args.destination}.")
            return 0
        previous, previous_files = load_awards(args.previous)
        latest, latest_files = load_awards(args.latest)
        result = compare(previous, latest, CUTOFFS)
    except (ValueError, TypeError, OSError, KeyError) as exc:
        print(f"Snapshot operation blocked: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps({**result, "previous_pages": previous_files, "latest_pages": latest_files}, indent=2))
    else:
        print(f"Capture changes: {result['added_activities']} activities added, {result['removed_activities']} removed.")
        for row in result["cutoffs"]:
            changed = len(row["worksheet_changes"])
            print(f"{row['cutoff']}: {changed} affected worksheet/category pairs | net USD {money(row['total_delta_cents'])}")
    return int(any(row["worksheet_changes"] for row in result["cutoffs"]))


if __name__ == "__main__":
    sys.exit(main())
