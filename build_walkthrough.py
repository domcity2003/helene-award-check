"""Generate the offline walkthrough from the verified Python results."""

import json
from pathlib import Path

from awards import load_awards
from check import DATA, load_draft, reconcile, review
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

    evidence = {
        "cutoff": CUTOFF, "initial": compact(results), "corrected": compact(corrected),
        "published_source": published[-1]["published_source"], "source_pages": pages,
        "investigation": investigate(records),
    }
    payload = json.dumps(evidence, ensure_ascii=True, separators=(",", ":")).replace("<", "\\u003c")
    template = (ROOT / "walkthrough.template.html").read_text(encoding="utf-8")
    return template.replace("<!-- WALKTHROUGH_DATA -->", payload)


if __name__ == "__main__":
    (ROOT / "walkthrough.html").write_text(build(), encoding="utf-8", newline="\n")
