"""Compare the existing award calculation with a fourth published quarter."""

import sys

from awards import load_awards
from check import DATA, june_comparison, money, round_dollars


def main():
    try:
        records, _ = load_awards(DATA / "openfema")
        result = june_comparison(records, DATA)
    except (KeyError, OSError, TypeError, ValueError) as exc:
        print(f"Validation blocked: {exc}", file=sys.stderr)
        return 2

    balances = result["category_cents"]
    published = result["published_category_dollars"]
    print(f"DR-4827-NC | {result['cutoff']} | {result['records_through_cutoff']:,} activities through cutoff")
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
