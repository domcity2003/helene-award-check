"""Validate a draft Helene Public Assistance briefing against OpenFEMA."""

import argparse
from collections import defaultdict
import csv
import json
from pathlib import Path
import re
import sys

from awards import AwardError, CATEGORIES, SOURCE_BASE, SOURCE_PATH, cutoff_balance, load_awards


DATA = Path(__file__).resolve().parent / "data"
INPUT_FIELDS = ["line_id", "scope", "key", "proposed_usd"]
CENT_CUTOFFS = ("2025-09-30", "2025-12-31", "2026-03-31")
JUNE_CUTOFF = "2026-06-30"
CUTOFFS = (*CENT_CUTOFFS, JUNE_CUTOFF)


class ReviewError(ValueError):
    """The draft or its source evidence cannot be reviewed."""


def cents(value):
    if not isinstance(value, str) or not re.fullmatch(r"-?(?:0|[1-9][0-9]{0,14})(?:\.[0-9]{1,2})?", value):
        raise ReviewError("Enter USD as a plain decimal with at most two decimal places.")
    whole, _, fraction = value.lstrip("-").partition(".")
    result = int(whole) * 100 + int(fraction.ljust(2, "0"))
    return -result if value.startswith("-") else result


def money(amount):
    dollars, remainder = divmod(abs(amount), 100)
    return f"{'-' if amount < 0 else ''}{dollars:,}.{remainder:02d}"


def round_dollars(cents):
    """Round signed cents to whole dollars, with ties away from zero."""
    magnitude = (abs(cents) + 50) // 100
    return -magnitude if cents < 0 else magnitude


def load_draft(path):
    rows = []
    seen = set()
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle, strict=True)
        if reader.fieldnames != INPUT_FIELDS:
            raise ReviewError(f"Expected CSV header {','.join(INPUT_FIELDS)}.")
        for row in reader:
            try:
                if None in row or None in row.values():
                    raise ReviewError("Expected exactly four fields.")
                line_id, scope, key, proposed = (row[field] for field in INPUT_FIELDS)
                if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}", line_id):
                    raise ReviewError("Use a line ID of 1-64 letters, digits, dots, underscores or hyphens, starting with a letter or digit.")
                if line_id in seen:
                    raise ReviewError(f"Repeated line ID {line_id}.")
                if scope == "worksheet" and re.fullmatch(r"[1-9][0-9]{0,9}", key):
                    key = int(key)
                elif scope == "category" and key in CATEGORIES:
                    pass
                elif scope == "total" and key == "all":
                    pass
                else:
                    raise ReviewError("Use worksheet with a positive project number, category with a FEMA category code, or total with all.")
                rows.append((line_id, scope, key, cents(proposed)))
                seen.add(line_id)
            except ReviewError as exc:
                raise ReviewError(f"CSV line {reader.line_num}: {exc}") from exc
    if not rows:
        raise ReviewError("The draft contains no figures.")
    return rows


def reconcile(records, data):
    reference = json.loads((data / "published-balances.json").read_text(encoding="utf-8"))
    if reference["disaster"] != "DR-4827-NC" or reference["currency"] != "USD" or reference["categories"] != CATEGORIES:
        raise ReviewError("Published reference has the wrong disaster, currency or categories.")
    snapshots = reference["snapshots"]
    if tuple(snapshot["cutoff"] for snapshot in snapshots) != CENT_CUTOFFS:
        raise ReviewError("Published reference must contain the three supported cutoffs in order.")
    result = []
    identities = defaultdict(set)
    for record in records:
        identities[record["worksheet"]].add((record["applicant_id"], record["category_code"]))
    ambiguous = sorted(key for key, values in identities.items() if len(values) > 1)
    if ambiguous:
        raise ReviewError(f"Worksheet numbers span multiple applicant/category pairs: {ambiguous}. Resolve their identity before reviewing figures.")
    for snapshot in snapshots:
        cutoff = snapshot["cutoff"]
        amounts = snapshot["amounts"]
        if amounts.keys() != CATEGORIES.keys():
            raise ReviewError(f"Published reference for {cutoff} must contain exactly the eight category codes.")
        actual, count = cutoff_balance(records, cutoff)
        for code, balance in actual.items():
            expected = cents(amounts[code])
            if balance != expected:
                raise ReviewError(f"Published balance disagrees for {cutoff} category {code} by {money(balance - expected)} USD.")
        result.append({
            "cutoff": cutoff,
            "records_through_cutoff": count,
            "total_cents": sum(actual.values()),
            "category_cents": actual,
            "published_precision": "cent",
            "published_source": {
                "url": snapshot["url"],
                "printed_pages": snapshot["printed_pages"],
                "pdf_pages": snapshot["pdf_pages"],
                "pdf_sha256": snapshot["sha256"],
            },
        })
    return result


def june_comparison(records, data):
    fixture = json.loads((data / "june-holdout.json").read_text(encoding="utf-8"))
    cutoff = fixture["cutoff"]
    published = fixture["fema_obligations_usd_whole_dollars"]
    if fixture["disaster"] != "DR-4827-NC" or cutoff != JUNE_CUTOFF:
        raise ReviewError("Unexpected disaster or cutoff in the June reference.")
    if (
        not isinstance(published, dict)
        or published.keys() != CATEGORIES.keys()
        or any(type(value) is not int for value in published.values())
    ):
        raise ReviewError("June reference must have eight whole-dollar category figures.")
    balances, count = cutoff_balance(records, cutoff)
    source = fixture["published_source"]
    return {
        "cutoff": cutoff,
        "records_through_cutoff": count,
        "total_cents": sum(balances.values()),
        "category_cents": balances,
        "published_precision": "dollar",
        "published_category_dollars": published,
        "published_source": {
            "url": source["url"],
            "printed_pages": [source["printed_page"]],
            "pdf_pages": [source["pdf_page"]],
            "pdf_sha256": source["pdf_sha256"],
        },
    }


def audit_history(records, data):
    """Compare earlier published observations without authorizing draft review."""
    fixture = json.loads((data / "historical-observations.json").read_text(encoding="utf-8"))
    if fixture["disaster"] != "DR-4827-NC":
        raise ReviewError("Historical reference has the wrong disaster.")
    results = []
    for report in fixture["reports"]:
        cutoff = report["cutoff"]
        balances, _ = cutoff_balance(records, cutoff)
        for code, raw in report["amounts"].items():
            balance = balances[code]
            try:
                # Verify grouping before removing commas from the transcription.
                if not re.fullmatch(r"\$[1-9][0-9]{0,2}(?:,[0-9]{3})*\.[0-9]{2}", raw):
                    raise ReviewError("Malformed source amount.")
                expected = cents(raw[1:].replace(",", ""))
            except ReviewError:
                difference = None
                status = "invalid_published_amount"
            else:
                difference = balance - expected
                status = "mismatch" if difference else "match"
            results.append({
                "cutoff": cutoff, "category": code, "status": status,
                "published_amount": raw, "rebuilt_cents": balance,
                "rebuilt_less_published_cents": difference,
                "published_source": report["source"],
            })
    if not results:
        raise ReviewError("Historical reference contains no observations.")
    return results


def coverage(records, cutoff):
    earlier = set()
    later_cents = defaultdict(int)
    for record in records:
        if record["date"] <= cutoff:
            earlier.add(record["worksheet"])
        else:
            later_cents[record["worksheet"]] += record["amount_cents"]
    return {
        "worksheets_at_cutoff": len(earlier),
        "worksheets_with_later_balance_change": sum(later_cents[key] != 0 for key in earlier),
        "worksheets_first_seen_after_cutoff": len(later_cents.keys() - earlier),
    }


def review(records, draft, cutoff):
    ledger = defaultdict(list)
    for record in sorted(records, key=lambda item: (item["date"], item["id"])):
        ledger["worksheet", record["worksheet"]].append(record)
        ledger["category", record["category_code"]].append(record)
        ledger["total", "all"].append(record)

    results = []
    for line_id, scope, key, proposed in draft:
        activity = ledger.get((scope, key), [])
        through = [record for record in activity if record["date"] <= cutoff]
        later = [record for record in activity if record["date"] > cutoff]
        supported = sum(record["amount_cents"] for record in through)
        later_net = sum(record["amount_cents"] for record in later)
        captured = supported + later_net
        difference = proposed - supported
        if scope == "worksheet" and not activity:
            status = "unknown_worksheet"
        elif scope == "worksheet" and not through:
            status = "no_activity_by_cutoff"
        elif difference == 0:
            status = "match"
        elif proposed == captured:
            status = "matches_later_balance"
        else:
            status = "mismatch"

        # An unknown key has no evidence. A known future worksheet has evidence
        # for its later activity, but no reportable worksheet balance at cutoff.
        reviewable = status not in {"unknown_worksheet", "no_activity_by_cutoff"}
        worksheet_source = None
        if scope == "worksheet":
            worksheet_source = f"{SOURCE_BASE}{SOURCE_PATH}?%24filter=disasterNumber%20eq%204827%20and%20pwNumber%20eq%20{key}"
        results.append({
            "line_id": line_id,
            "scope": scope,
            "key": key,
            "status": status,
            "proposed_cents": proposed,
            "supported_cents": supported if reviewable else None,
            "difference_cents": difference if reviewable else None,
            "captured_cents": captured if activity else None,
            "later_net_cents": later_net if activity else None,
            "worksheet_source": worksheet_source,
            "through_cutoff": through,
            "after_cutoff": later,
        })
    return results


def print_review(results, cutoff):
    print(f"DR-4827-NC | federal obligations through {cutoff} | USD")
    width = max(10, max(len(row["line_id"]) for row in results))
    print(f"{'Draft line':<{width}} {'Result':<23} {'Proposed':>21} {'Supported':>21} {'Proposed less supported':>23}")
    for row in results:
        columns = [money(row[key]) if row[key] is not None else "--" for key in (
            "proposed_cents", "supported_cents", "difference_cents",
        )]
        print(f"{row['line_id']:<{width}} {row['status']:<23} {columns[0]:>21} {columns[1]:>21} {columns[2]:>23}")
        if row["status"] == "matches_later_balance":
            print(f"  {len(row['after_cutoff'])} later transactions net to {money(row['later_net_cents'])} USD.")
            if len(row["after_cutoff"]) <= 5:
                for event in row["after_cutoff"]:
                    print(f"  {event['date']}  PW {event['worksheet']}  v{event['version']}  {money(event['amount_cents'])} USD")
    matched = sum(row["status"] == "match" for row in results)
    print(f"\n{matched}/{len(results)} match. {len(results) - matched} need review.")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=DATA, help="Directory holding the pinned source data")
    commands = parser.add_subparsers(dest="command", required=True)
    audit = commands.add_parser("reconcile", help="Check the published balances for all four supported dates")
    history = commands.add_parser("audit-history", help="Show discrepancies in earlier published observations")
    batch = commands.add_parser("review", help="Check a draft briefing CSV")
    batch.add_argument("draft", type=Path)
    batch.add_argument("--as-of", required=True, choices=CUTOFFS)
    for command in (audit, batch, history):
        command.add_argument("--json", action="store_true", help="Write machine-readable evidence to stdout")
    args = parser.parse_args(argv)

    try:
        draft = load_draft(args.draft) if args.command == "review" else None
        records, sources = load_awards(args.data / "openfema")
        if args.command == "audit-history":
            observations = audit_history(records, args.data)
        else:
            published = reconcile(records, args.data)
            if args.command == "reconcile" or args.as_of == JUNE_CUTOFF:
                june = june_comparison(records, args.data)
                for code, balance in june["category_cents"].items():
                    difference = round_dollars(balance) - june["published_category_dollars"][code]
                    if difference:
                        raise ReviewError(f"Published balance disagrees for {JUNE_CUTOFF} category {code} by {difference:,} whole USD.")
                published.append(june)
    except (AwardError, ReviewError, csv.Error, KeyError, TypeError, UnicodeError, OSError, json.JSONDecodeError) as exc:
        print(f"Review blocked: {exc}", file=sys.stderr)
        return 2

    evidence = {
        "schema_version": 1,
        "disaster": "DR-4827-NC",
        "measure": "federal_share_obligated",
        "currency": "USD",
        "record_count": len(records),
        "source_pages": sources,
    }
    if args.command == "audit-history":
        if args.json:
            print(json.dumps({**evidence, "observations": observations}, indent=2))
        else:
            print(f"{'Cutoff':<10} {'Cat':<3} {'Published USD':>17} {'Rebuilt USD':>17} {'Difference USD':>16}  Result")
            for row in observations:
                delta = row["rebuilt_less_published_cents"]
                display = "--" if delta is None else money(delta)
                print(f"{row['cutoff']} {row['category']:<3} {row['published_amount']:>17} "
                      f"{money(row['rebuilt_cents']):>17} {display:>16}  {row['status']}")
        return int(any(row["status"] != "match" for row in observations))
    if args.command == "reconcile":
        if args.json:
            print(json.dumps({**evidence, "reconciliation": published}, indent=2))
        else:
            for row in published:
                print(f"{row['cutoff']}  ${money(row['total_cents']):>18}  8/8 match to the published {row['published_precision']}")
            print(f"32/32 balances match at published precision across {len(records):,} captured award activities.")
        return 0

    results = review(records, draft, args.as_of)
    if args.json:
        print(json.dumps({
            **evidence, "as_of": args.as_of, "reconciliation": published,
            "coverage": coverage(records, args.as_of), "results": results,
        }, indent=2))
    else:
        print_review(results, args.as_of)
    return int(any(row["status"] != "match" for row in results))


if __name__ == "__main__":
    sys.exit(main())
