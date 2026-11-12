"""Compare the existing award calculation with a fourth published quarter."""

import json
import sys

from awards import CATEGORIES, cutoff_balance, load_awards
from check import DATA, money


def round_dollars(cents):
    """Round signed cents to whole dollars, with ties away from zero."""
    magnitude = (abs(cents) + 50) // 100
    return -magnitude if cents < 0 else magnitude


def main():
    try:
        fixture = json.loads((DATA / "june-holdout.json").read_text(encoding="utf-8"))
        cutoff = fixture["cutoff"]
        published = fixture["fema_obligations_usd_whole_dollars"]
        if fixture["disaster"] != "DR-4827-NC" or cutoff != "2026-06-30":
            raise ValueError("Unexpected disaster or cutoff in the June reference.")
        if (
            not isinstance(published, dict)
            or published.keys() != CATEGORIES.keys()
            or any(type(value) is not int for value in published.values())
        ):
            raise ValueError("June reference must have eight whole-dollar category figures.")
        records, _ = load_awards(DATA / "openfema")
        balances, count = cutoff_balance(records, cutoff)
    except (KeyError, OSError, TypeError, ValueError) as exc:
        print(f"Validation blocked: {exc}", file=sys.stderr)
        return 2

    print(f"DR-4827-NC | {cutoff} | {count:,} activities through cutoff")
    print(f"{'Category':<8} {'Rebuilt USD':>16} {'Rounded USD':>16} {'Published USD':>16} {'Result':>8}")
    matched = 0
    for category, balance in balances.items():
        rounded = round_dollars(balance)
        expected = published[category]
        status = "match" if rounded == expected else "differs"
        matched += rounded == expected
        print(f"{category:<8} {money(balance):>16} {rounded:>16,} {expected:>16,} {status:>8}")
    print(f"\n{matched}/8 match at published precision. Exact FEMA ledger total: ${money(sum(balances.values()))}.")
    return 0 if matched == len(balances) else 1


if __name__ == "__main__":
    sys.exit(main())
