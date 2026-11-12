# Helene Award Check

Check the FEMA figures in a draft recovery briefing before it goes out. Give the checker a CSV and a quarter-end date. It returns the supported amounts, flags discrepancies, and shows which transactions support each result.

**Try the offline walkthrough.** Download `walkthrough.html` from the file page using **Download raw file**, then open it in your browser. Inspect the real debris removal discrepancy, correct the March practice draft, and download the corrected CSV and supporting evidence. The walkthrough embeds results calculated from the pinned data. Use the CLI to review your own files. [Walkthrough file](walkthrough.html).

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

Use `worksheet` with a FEMA project worksheet number, `category` with a Public Assistance category code, or `total` with `all`. Line IDs are unique within a draft. Enter plain USD amounts with up to two decimal places. Supported dates are **2025-09-30**, **2025-12-31**, **2026-03-31**, and **2026-06-30**. Draft checks use the ledger's exact cents at every cutoff. The June published reference is rounded separately.

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

The checker verifies the hashes, disaster scope, page counts, and record IDs of four [pinned OpenFEMA responses](data/openfema/acquisition.json). It sums signed award activity in integer cents through the inclusive UTC cutoff. Across four supported dates, **32 category balances match at published precision**: 24 to the cent and eight to the dollar.

| Cutoff | Federal obligations | Published appendix |
| --- | ---: | --- |
| Sep 30, 2025 | $784,000,491.00 | [FY26 Q1, pp. 64–65](https://www.wncrecovery.nc.gov/grow-nc-q1qr-2026/open#page=66) |
| Dec 31, 2025 | $983,639,539.91 | [FY26 Q2, pp. 57–58](https://www.wncrecovery.nc.gov/grow-nc-q2qr-2026/open#page=59) |
| Mar 31, 2026 | $1,530,247,208.35 | [FY26 Q3, p. 65](https://www.wncrecovery.nc.gov/grow-nc-q3qr-2026/open#page=67) |
| Jun 30, 2026 | $2,350,422,001.31 | [FY26 Q4, p. 65](https://www.wncrecovery.nc.gov/grow-nc-q4qr-2026/open#page=67) |

This work sample covers North Carolina Helene Public Assistance (DR-4827-NC) and measures federal obligations. Payment or reimbursement would require separate records. The tool reconstructs earlier balances using activity dates from a November 12, 2026 UTC capture. The published reports anchor the category totals for those dates. Project amounts are reconstructed from the FEMA activity records. [OpenFEMA dataset and field definitions](https://www.fema.gov/openfema-data-page/public-assistance-grant-award-activities-v2) · [Reference values and PDF hashes](data/published-balances.json).

## Fourth-quarter validation

**All eight June 30, 2026 categories matched to the published dollar** using the same award capture and cutoff calculation. The checker reconstructed $2,350,422,001.31 in FEMA obligations from 2,909 activities through June 30. The state report publishes whole-dollar figures, so this test compares each reconstructed category after rounding to the nearest dollar. Category A lands exactly on the half-dollar and rounds up. [June report, printed p. 65](https://www.wncrecovery.nc.gov/grow-nc-q4qr-2026/open#page=67).

The eight displayed FEMA rows sum to $2,350,422,002. The page also lists a HUD drawdown of $1,200,847, and its $2,351,622,848 grand total covers both programs. Adding the displayed rows yields $1 more than the grand total, consistent with independent rounding. The validation uses only the eight FEMA rows, as identified by the appendix footnote. [Transcribed figures and PDF hash](data/june-holdout.json).

Run `python validate_q4.py` to see the June comparison row by row. The calculation and capture were committed before the appendix figures were read. [Original calculation and capture](https://github.com/domcity2003/helene-award-check/commit/a81969a92188fd4792f2c15e0c3d4a60e1e2bfcf).

## Earlier reports and unresolved exceptions

Run `python check.py audit-history` for the two earlier reports. It returns exit code 1 when it finds a discrepancy or a malformed published amount. Add `--json` for the exact differences and report pages. Across nine observations, six matched, two differed, and one had malformed comma grouping.

| Cutoff | Category | Published | Rebuilt | Finding |
| --- | --- | ---: | ---: | --- |
| Mar 31, 2025 | B | $178,235,274.40 | $178,347,474.82 | Replay higher by $112,200.42 |
| Jun 30, 2025 | A | $135,411,671.81 | $131,346,970.47 | Replay lower by $4,064,701.34 |
| Jun 30, 2025 | G | `$65,33,975.79` | $6,533,975.79 | Malformed published grouping |

The March check uses the explicit Category B obligation in the narrative. The report labels the nearby table as expenditures and describes its overall Public Assistance figure inconsistently on page 16, so the audit includes only the Category B obligation from that report. The public records do not establish the cause of either difference. Both earlier dates require additional evidence before the checker can use them for draft review. [March report, pp. 15–16](https://www.wncrecovery.nc.gov/grow-nc-q3qr-2025/open#page=15) · [June report, p. 67](https://www.wncrecovery.nc.gov/grow-nc-q4qr-2025/open#page=69).

### Investigating the June debris removal difference

```sh
python investigate.py
python investigate.py --json > june-investigation.json
```

The replay sums 122 signed activities across 121 worksheets through June 30. The following seven days add $134,219.98. Using dates through the August 15 publication still leaves $1,955,589.26 unexplained. No single checked transaction, worksheet balance through June 30, or later cutoff through publication equals the published difference. The JSON includes every activity used, the source page and hash, and the exact Grants Portal export needed for a worksheet-by-worksheet comparison. The command returns exit code 1 while the difference is unresolved. [June report, p. 67](https://www.wncrecovery.nc.gov/grow-nc-q4qr-2025/open#page=69).

### Comparing successive OpenFEMA captures

```sh
python snapshots.py capture captures/new
python snapshots.py compare captures/new --json > capture-comparison.json
```

The default baseline is the repository's pinned capture. Use `--previous captures/older` to compare two downloads. Each capture saves the raw responses and hash manifest to a fresh directory after verifying scope and pagination. Comparison uses worksheet, applicant, category, effective date, version and signed cents. It preserves repeated activities and ignores changes to public row IDs. The JSON shows additions and removals and the before-and-after balances by reporting date. Exit code 1 means at least one supported cutoff has changed activity, including changes that net to zero. Exit code 2 means the operation could not be verified.

The first live verification fetched 3,384 records and found zero financial differences from the pinned capture. The tests also check a controlled revision and confirm that the dates before and after it report the expected balances.

Run `python -m unittest -v` to reproduce the QA checks. They cover signed reductions, one-cent discrepancies, unknown and future worksheets, invalid input, source tampering, rounding, and the historical exceptions. GitHub Actions runs the checks on Windows and Linux.

Regenerate the walkthrough after changing its template or evidence with `python build_walkthrough.py`.
