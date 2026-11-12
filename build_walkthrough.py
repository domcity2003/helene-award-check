"""Generate the offline walkthrough from the verified Python results."""

import json
from pathlib import Path

from awards import CATEGORIES, load_awards
from check import DATA, audit_history, june_comparison, load_draft, money, reconcile, review, round_dollars
from investigate import investigate


ROOT = Path(__file__).resolve().parent
CUTOFF = "2026-03-31"


def build():
    records, pages = load_awards(DATA / "openfema")
    published = reconcile(records, DATA)
    draft = load_draft(ROOT / "examples" / "march-draft.csv")
    results = review(records, draft, CUTOFF)
    reviewed = [(row["line_id"], row["scope"], row["key"], row["supported_cents"]) for row in results]
    corrected = review(records, reviewed, CUTOFF)
    if any(row["status"] != "match" for row in corrected):
        raise ValueError("The walkthrough requires a fully corrected sample.")

    def compact(rows):
        for row in rows:
            for field in ("through_cutoff", "after_cutoff"):
                row[f"{field}_count"] = len(row[field])
                if row["scope"] != "worksheet":
                    del row[field]
        return rows

    investigation = investigate(records)
    historical = [row for row in audit_history(records, DATA)
                  if row["cutoff"] == investigation["observation"]["cutoff"]]
    march_report = next(row for row in published if row["cutoff"] == CUTOFF)
    june_report = june_comparison(records, DATA)
    for report in (march_report, june_report):
        whole_dollars = report["published_precision"] == "dollar"
        for code, balance in report["category_cents"].items():
            published_cents = report["published_category_dollars"][code] * 100 if whole_dollars else balance
            compared_cents = round_dollars(balance) * 100 if whole_dollars else balance
            difference = compared_cents - published_cents
            historical.append({
                "cutoff": report["cutoff"], "category": code,
                "status": "mismatch" if difference else "match",
                "published_amount": f"${published_cents // 100:,}" if whole_dollars else f"${money(published_cents)}",
                "rebuilt_cents": balance, "rebuilt_less_published_cents": difference,
                "published_precision": report["published_precision"],
                "published_source": report["published_source"],
            })
    evidence = {
        "cutoff": CUTOFF, "initial": compact(results), "corrected": compact(corrected),
        "published_source": march_report["published_source"],
        "source_pages": pages, "investigation": investigation,
        "historical": historical, "categories": CATEGORIES,
    }
    payload = json.dumps(evidence, ensure_ascii=True, separators=(",", ":")).replace("<", "\\u003c")
    template = (ROOT / "walkthrough.template.html").read_text(encoding="utf-8")
    return template.replace("<!-- WALKTHROUGH_DATA -->", payload)


if __name__ == "__main__":
    (ROOT / "walkthrough.html").write_text(build(), encoding="utf-8", newline="\n")
