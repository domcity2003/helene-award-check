# Helene Award Check

Check the FEMA figures in a draft recovery briefing before it goes out. Give the checker a CSV and a quarter-end date. It returns the supported amounts, flags discrepancies, and shows which transactions support each result.

**In the March example, a draft uses $286,345,207.02 for one North Carolina Emergency Management project. The amount as of March 31 was $200,013,459.45.** Two later transactions explain the entire $86,331,747.57 difference. The example draft intentionally uses the wrong balance from real FEMA records.

## Run the example

Python 3.10 or newer. From the repo root, with no packages to install or API keys to set:

```sh
python check.py reconcile
python check.py review examples/march-draft.csv --as-of 2026-03-31
python check.py review examples/march-reviewed.csv --as-of 2026-03-31
```

| Draft line | Proposed | Supported on March 31 | Outcome |
| --- | ---: | ---: | --- |
| NC Emergency Management · PW 4341 | $286,345,207.02 | $200,013,459.45 | $86,331,747.57 over |
| Madison County · PW 370 | $860,703.03 | $860,703.03 | Matches after a $775,994.30 reduction |
| Emergency Protective Measures · Category B | $572,529,086.68 | $572,529,086.68 | Matches |
| North Carolina · FEMA Public Assistance total | $1,530,247,208.35 | $1,530,247,208.35 | Matches |

For PW 4341 the output lists **+$80,000,228.17 on April 23** and **+$6,331,519.40 on October 21**. The corrected draft passes all four checks. [FEMA record query for PW 4341](https://www.fema.gov/api/open/v2/PublicAssistanceGrantAwardActivities?%24filter=disasterNumber%20eq%204827%20and%20pwNumber%20eq%204341).

The same cutoff affected more than the example row. Of 2,339 worksheets with March 31 activity, 131 had a different balance by the capture date. Another 762 first appeared after March 31. The JSON output reports these counts for the selected cutoff.

## Check your own draft

```csv
line_id,scope,key,proposed_usd
project-4341,worksheet,4341,200013459.45
emergency-work,category,B,572529086.68
statewide,total,all,1530247208.35
```

Use `worksheet` with a FEMA project worksheet number, `category` with a Public Assistance category code, or `total` with `all`. Line IDs are unique within a draft. Enter plain USD amounts with up to two decimal places. Supported dates are **2025-09-30**, **2025-12-31**, and **2026-03-31**.

```sh
python check.py review examples/march-draft.csv --as-of 2026-03-31 --json > review.json
```

The JSON records the proposed and supported amounts in integer cents, every included and later transaction, and the capture hashes and report pages used for verification. `matches_later_balance` means the proposed figure equals the balance at capture and differs from the balance at the selected cutoff. An unknown worksheet and a worksheet with only later activity each need review, even when the draft says zero.

| Exit code | Meaning |
| --- | --- |
| `0` | Every draft figure matched, or reconciliation passed |
| `1` | The checker returned results and at least one figure needs review |
| `2` | Input or evidence validation blocked the run |

## Evidence and scope

The checker verifies the hashes, disaster scope, page counts, and record IDs of four [pinned OpenFEMA responses](data/openfema/acquisition.json). It sums signed award activity in integer cents through the inclusive UTC cutoff, then checks each of the eight categories against three published North Carolina quarter ends. **All 24 balances match to the cent**, across 3,384 award activities.

| Cutoff | Federal obligations | Published appendix |
| --- | ---: | --- |
| Sep 30, 2025 | $784,000,491.00 | [FY26 Q1, pp. 64–65](https://www.wncrecovery.nc.gov/grow-nc-q1qr-2026/open#page=66) |
| Dec 31, 2025 | $983,639,539.91 | [FY26 Q2, pp. 57–58](https://www.wncrecovery.nc.gov/grow-nc-q2qr-2026/open#page=59) |
| Mar 31, 2026 | $1,530,247,208.35 | [FY26 Q3, p. 65](https://www.wncrecovery.nc.gov/grow-nc-q3qr-2026/open#page=67) |

This work sample covers North Carolina Helene Public Assistance (DR-4827-NC) and measures federal obligations. Payment or reimbursement would require separate records. The tool reconstructs earlier balances using activity dates from a November 12, 2026 UTC capture. The published reports anchor the category totals for those dates. Project amounts are reconstructed from the FEMA activity records. [OpenFEMA dataset and field definitions](https://www.fema.gov/openfema-data-page/public-assistance-grant-award-activities-v2) · [Reference values and PDF hashes](data/published-balances.json).

Run `python -m unittest -v` to reproduce the QA checks. They cover the example and its correction, signed reductions, an exact one-cent discrepancy, unknown and future worksheets, invalid input, source tampering, and disagreement with a published total. GitHub Actions runs the checks on Windows and Linux.
