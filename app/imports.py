"""Validation for CSV imports. Pure functions, no Flask or DB access, so they are easy to test.

The browser editor runs the same rules for instant feedback (frontend/src/lib/validate.ts);
the server always re-validates because client input is never trusted.
"""
import re
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional

EMAIL_RE = re.compile(r"^[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?)+$")
URL_RE = re.compile(r"^https?://[^\s/$.?#][^\s]*$", re.IGNORECASE)

VOTER_FIELDS = ["name", "email"]
CANDIDATE_FIELDS = ["position", "name", "bio", "photo_url"]

HEADER_ALIASES: Dict[str, set] = {
    "name": {"name", "full name", "fullname", "voter", "voter name", "candidate", "candidate name", "member"},
    "email": {"email", "e-mail", "email address", "mail", "e mail"},
    "position": {"position", "role", "office", "post", "seat", "title"},
    "bio": {"bio", "description", "about", "manifesto", "summary", "statement"},
    "photo_url": {"photo_url", "photo", "image", "image_url", "photo url", "picture", "avatar", "headshot"},
}

MAX_LEN = {"name": 128, "email": 255, "position": 128, "bio": 2000, "photo_url": 255}


def normalize_header(raw: Optional[str]) -> Optional[str]:
    """Maps a spreadsheet header to a canonical field name, or None if unrecognised."""
    key = re.sub(r"[\s_\-]+", " ", (raw or "").strip().lower())
    for canonical, aliases in HEADER_ALIASES.items():
        if key in aliases or key.replace(" ", "_") == canonical:
            return canonical
    return None


def clean(value) -> str:
    return re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", str(value or "")).strip()


def is_valid_email(value: str) -> bool:
    return bool(value) and len(value) <= MAX_LEN["email"] and bool(EMAIL_RE.match(value))


def csv_safe(value) -> str:
    """Neutralise spreadsheet formula injection when exporting."""
    text = "" if value is None else str(value)
    if text and text[0] in "=+-@\t\r":
        return "'" + text
    return text


@dataclass
class RowResult:
    index: int
    row: Dict[str, str]
    errors: Dict[str, str] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not self.errors

    def as_dict(self) -> dict:
        return {"index": self.index, "row": self.row, "errors": self.errors}


@dataclass
class Report:
    rows: List[RowResult]
    new_positions: List[dict] = field(default_factory=list)

    @property
    def valid(self) -> List[RowResult]:
        return [r for r in self.rows if r.ok]

    @property
    def invalid(self) -> List[RowResult]:
        return [r for r in self.rows if not r.ok]

    def as_dict(self) -> dict:
        return {
            "total": len(self.rows),
            "valid": len(self.valid),
            "invalid": len(self.invalid),
            "rows": [r.as_dict() for r in self.rows],
            "new_positions": self.new_positions,
        }


def _normalise_row(raw: dict, fields: Iterable[str]) -> Dict[str, str]:
    return {f: clean(raw.get(f, "")) for f in fields}


def _check_length(result: RowResult) -> None:
    for name, limit in MAX_LEN.items():
        value = result.row.get(name)
        if value and len(value) > limit and name not in result.errors:
            result.errors[name] = f"Too long (max {limit} characters)"


def validate_voters(rows: List[dict], existing_emails: Iterable[str]) -> Report:
    existing = {e.lower() for e in existing_emails if e}
    seen: Dict[str, int] = {}
    results: List[RowResult] = []
    for i, raw in enumerate(rows):
        result = RowResult(i, _normalise_row(raw or {}, VOTER_FIELDS))
        email = result.row["email"]
        if not email:
            result.errors["email"] = "Email is required"
        elif not is_valid_email(email):
            result.errors["email"] = "Not a valid email address"
        elif email.lower() in existing:
            result.errors["email"] = "Already invited to this election"
        elif email.lower() in seen:
            result.errors["email"] = f"Duplicate of row {seen[email.lower()] + 1}"
        else:
            seen[email.lower()] = i
        _check_length(result)
        results.append(result)
    return Report(results)


def validate_candidates(rows: List[dict], positions: Dict[str, dict], create_missing: bool = False) -> Report:
    """`positions` maps lower-cased position name -> {"name", "slots", "names": set(lower candidate names)}."""
    state = {k: {"name": v["name"], "slots": v["slots"], "names": set(v["names"]), "count": len(v["names"])}
             for k, v in positions.items()}
    new_positions: Dict[str, dict] = {}
    results: List[RowResult] = []
    parsed: List[RowResult] = []
    for i, raw in enumerate(rows):
        result = RowResult(i, _normalise_row(raw or {}, CANDIDATE_FIELDS))
        parsed.append(result)

    if create_missing:
        for result in parsed:
            pname = result.row["position"]
            key = pname.lower()
            if pname and key not in state:
                new_positions.setdefault(key, {"name": pname, "slots": 0})
            if pname and key in new_positions:
                new_positions[key]["slots"] += 1

    for result in parsed:
        row = result.row
        pname, cname, key = row["position"], row["name"], row["position"].lower()
        if not pname:
            result.errors["position"] = "Position is required"
        elif key not in state and key not in new_positions:
            result.errors["position"] = "Unknown position (turn on 'create missing positions' or fix the name)"
        if not cname:
            result.errors["name"] = "Name is required"
        if row["photo_url"] and not URL_RE.match(row["photo_url"]):
            result.errors["photo_url"] = "Must be a full http(s) link"
        _check_length(result)

        if "position" not in result.errors and "name" not in result.errors:
            if key not in state:
                state[key] = {"name": new_positions[key]["name"], "slots": new_positions[key]["slots"],
                              "names": set(), "count": 0}
            pos = state[key]
            if cname.lower() in pos["names"]:
                result.errors["name"] = f"Already a candidate for {pos['name']}"
            elif pos["count"] >= pos["slots"]:
                result.errors["position"] = f"{pos['name']} is full ({pos['slots']} slot{'s' if pos['slots'] != 1 else ''})"
            else:
                pos["names"].add(cname.lower())
                pos["count"] += 1
        results.append(result)
    return Report(results, list(new_positions.values()))
