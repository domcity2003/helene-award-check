"""Reconcile signed OpenFEMA award activities to published obligation balances."""

from datetime import date, datetime, timezone
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import re
from urllib.parse import parse_qs, urlsplit
from uuid import UUID

CATEGORIES = {
    "A": "Debris Removal",
    "B": "Emergency Protective Measures",
    "C": "Roads and Bridges",
    "D": "Water Control Facilities",
    "E": "Buildings and Equipment",
    "F": "Utilities",
    "G": "Parks, Recreational Facilities, and Other Items",
    "Z": "Management Costs",
}


DATASET = "PublicAssistanceGrantAwardActivities"
SOURCE_BASE = "https://www.fema.gov"
SOURCE_PATH = f"/api/open/v2/{DATASET}"
SOURCE_URL = "https://www.fema.gov/openfema-data-page/public-assistance-grant-award-activities-v2"
PAGE_SIZE = 1000


class AwardError(ValueError):
    """The OpenFEMA capture could not be validated."""


def _read_json(path: Path, expected_digest: str | None = None):
    try:
        payload = path.read_bytes()
        if expected_digest is not None and hashlib.sha256(payload).hexdigest() != expected_digest:
            raise AwardError(f"{path.name} differs from the acquisition manifest. Restore the recorded source file.")
        return json.loads(payload.decode("utf-8-sig"), parse_float=Decimal)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise AwardError(f"Cannot read {path.name}. Restore the OpenFEMA source packet.") from exc


def _manifest_pages(directory: Path) -> list[dict]:
    manifest = _read_json(directory / "acquisition.json")
    if not isinstance(manifest, dict) or manifest.get("source_base") != SOURCE_BASE:
        raise AwardError("OpenFEMA acquisition manifest has an unexpected source. Restore the source packet.")
    files = manifest.get("files")
    if not isinstance(files, list) or not all(isinstance(entry, dict) for entry in files):
        raise AwardError("OpenFEMA acquisition manifest lacks file entries. Restore the source packet.")

    pages = []
    for entry in files:
        name = entry.get("filename")
        if name in ("cat-b-worksheets.json", "field-dictionary-v2.json"):
            # The worksheet lookup and schema document are separate source material.
            continue
        if not isinstance(name, str) or not re.fullmatch(r"award-(0|[1-9][0-9]*)\.json", name):
            raise AwardError("OpenFEMA acquisition manifest has an unexpected filename. Restore the source packet.")
        pages.append(entry)
    if not pages:
        raise AwardError("OpenFEMA acquisition manifest lists no award pages. Restore the source packet.")
    return sorted(pages, key=lambda entry: int(entry["filename"][6:-5]))


def _read_award_page(directory: Path, entry: dict, skip: int) -> tuple[list[dict], int]:
    name = f"award-{skip}.json"
    if entry["filename"] != name:
        raise AwardError(f"Missing or repeated OpenFEMA page at offset {skip}. Restore the complete source packet.")
    digest = entry.get("sha256")
    if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise AwardError(f"{name} has no valid SHA-256 in the acquisition manifest. Restore the manifest.")
    data = _read_json(directory / name, digest)
    if not isinstance(data, dict):
        raise AwardError(f"{name} has an unexpected response format. Restore the original OpenFEMA response.")
    meta = data.get("metadata")
    rows = data.get(DATASET)
    if not isinstance(meta, dict) or not isinstance(rows, list):
        raise AwardError(f"{name} lacks OpenFEMA award rows or metadata. Restore the original response.")

    url = entry.get("url")
    relative_url = meta.get("url")
    if (
        not isinstance(relative_url, str)
        or not relative_url.startswith(SOURCE_PATH + "?")
        or url != SOURCE_BASE + relative_url
    ):
        raise AwardError(f"{name} has inconsistent request provenance. Check the acquisition manifest.")
    parsed = urlsplit(relative_url)
    expected_query = {
        "$filter": ["disasterNumber eq 4827"],
        "$top": [str(PAGE_SIZE)],
        "$count": ["true"],
        "$orderby": ["id"],
        "$skip": [str(skip)],
    }
    if (
        parsed.path != SOURCE_PATH
        or parsed.fragment
        or parse_qs(parsed.query, keep_blank_values=True) != expected_query
        or meta.get("entityname") != DATASET
        or meta.get("version") != "v2"
        or meta.get("filter") != "disasterNumber eq 4827"
        or meta.get("skip") != skip
        or meta.get("top") != PAGE_SIZE
        or meta.get("orderby") != "id ASC"
        or not meta.get("rundate")
        or entry.get("retrieved_utc") != meta["rundate"]
    ):
        raise AwardError(f"{name} has unexpected request metadata. Restore the DR-4827-NC query responses.")

    count = meta.get("count")
    if (
        type(count) is not int
        or count <= skip
        or count != entry.get("reported_count")
        or len(rows) != entry.get("row_count")
        or len(rows) != min(PAGE_SIZE, count - skip)
    ):
        raise AwardError(f"{name} has inconsistent row counts. Check whether the acquisition was incomplete.")
    return rows, count


def _normalize(row: dict, source_url: str) -> dict:
    if not isinstance(row, dict):
        raise AwardError("OpenFEMA returned an invalid award row. Restore the source packet.")
    record_id = row.get("id")
    try:
        if not isinstance(record_id, str) or str(UUID(record_id)) != record_id:
            raise ValueError("Expected a canonical UUID")
    except ValueError as exc:
        raise AwardError("OpenFEMA returned a row without a valid record ID. Restore the source packet.") from exc

    if (
        row.get("disasterNumber") != 4827
        or row.get("disasterType") != "DR"
        or row.get("stateAbbreviation") != "NC"
        or row.get("eligibilityStatus") != "E"
        or row.get("fundingStatus") != "O"
    ):
        raise AwardError(f"OpenFEMA record {record_id} has unexpected disaster or obligation status. Check its scope.")
    category = row.get("damageCategoryCode")
    code = category[:1] if isinstance(category, str) else ""
    if code not in CATEGORIES or category != f"{code} - {CATEGORIES[code]}":
        raise AwardError(f"OpenFEMA record {record_id} has an unknown Public Assistance category. Review the source row.")

    try:
        raw_timestamp = row["dateObligated"]
        if not isinstance(raw_timestamp, str):
            raise ValueError("Expected an ISO timestamp")
        # Python 3.10 requires an explicit offset in place of the UTC suffix.
        if raw_timestamp.endswith("Z"):
            raw_timestamp = raw_timestamp[:-1] + "+00:00"
        timestamp = datetime.fromisoformat(raw_timestamp)
        if timestamp.tzinfo is None:
            raise ValueError("Missing timezone")
        effective_date = timestamp.astimezone(timezone.utc).date()
        if effective_date < date(2024, 9, 28):
            raise ValueError("Predates declaration")
    except (KeyError, TypeError, ValueError) as exc:
        raise AwardError(f"OpenFEMA record {record_id} has an invalid obligation date. Review the source row.") from exc

    amount = row.get("federalShareObligated")
    if type(amount) not in (int, Decimal) or not Decimal(amount).is_finite():
        raise AwardError(f"OpenFEMA record {record_id} has an invalid federal share. Review the source row.")
    numerator, denominator = Decimal(amount).as_integer_ratio()
    cents, remainder = divmod(numerator * 100, denominator)
    if remainder:
        raise AwardError(f"OpenFEMA record {record_id} has a federal share below cent precision. Review the source row.")

    worksheet = row.get("pwNumber")
    version = row.get("versionNumber")
    if type(worksheet) is not int or worksheet < 1 or type(version) is not int or version < 0:
        raise AwardError(f"OpenFEMA record {record_id} has an invalid worksheet or version. Review the source row.")
    for field in ("applicantName", "applicantId", "projectTitle"):
        if not isinstance(row.get(field), str) or not row[field].strip():
            raise AwardError(f"OpenFEMA record {record_id} has a missing {field}. Review the source row.")

    return {
        "id": record_id,
        "date": effective_date.isoformat(),
        "category_code": code,
        "amount_cents": cents,
        "worksheet": worksheet,
        "version": version,
        "applicant": row["applicantName"],
        "applicant_id": row["applicantId"],
        "project": row["projectTitle"],
        "source_url": source_url,
    }


def load_awards(directory: Path) -> tuple[list[dict], list[dict]]:
    entries = _manifest_pages(directory)
    records = []
    previous_id = ""
    total_count = None
    for page_index, entry in enumerate(entries):
        rows, count = _read_award_page(directory, entry, skip=page_index * PAGE_SIZE)
        if total_count is not None and count != total_count:
            raise AwardError("OpenFEMA count changed across pages. Reacquire the complete source packet together.")
        total_count = count
        for raw in rows:
            record = _normalize(raw, entry["url"])
            record_id = record["id"]
            if record_id == previous_id:
                raise AwardError(f"Duplicate OpenFEMA record ID {record_id}. Check pagination.")
            if record_id < previous_id:
                raise AwardError(f"OpenFEMA record {record_id} is out of ID order or repeated. Check pagination.")
            previous_id = record_id
            records.append(record)
    if len(records) != total_count:
        raise AwardError("OpenFEMA page count is incomplete. Restore all award pages from the manifest.")
    return records, entries


def cutoff_balance(records: list[dict], cutoff: str) -> tuple[dict[str, int], int]:
    balances = dict.fromkeys(CATEGORIES, 0)
    count = 0
    for record in records:
        if record["date"] <= cutoff:
            balances[record["category_code"]] += record["amount_cents"]
            count += 1
    return balances, count
