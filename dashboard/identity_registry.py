"""
Account Identity Registry and Entity Resolution Governance Module.
Pure functional presentation-layer module for:
  - Validating and parsing Account Identity Crosswalk CSVs (with utf-8-sig BOM handling)
  - Multi-tier validation: complete-file rejection (fatal) vs non-ambiguous row quarantine
  - Fail-closed normalized collision detection across accounts (aliases, domains, tickers)
  - Canonical account ID & name consistency enforcement
  - Strict match routes (NORMALIZED_CANONICAL_NAME, APPROVED_ALIAS, APPROVED_DOMAIN,
    APPROVED_TICKER, APPROVED_PARENTHETICAL_TICKER)
  - Full-field equality enforcement (strictly prohibiting substring containment)
  - Parenthetical ticker token parsing
  - Row-level match lineage and pre-scoring integrity assertions
"""

import csv
import io
import re
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple, Union

# Canonical CSV schema definition (required columns)
REQUIRED_CROSSWALK_COLUMNS = [
    "canonical_account_id",
    "canonical_company_name",
    "approved_alias",
    "approved_domain",
    "approved_ticker",
    "approval_status",
    "approved_by",
    "approved_at",
]

# Supported approval status vocabulary
SUPPORTED_STATUSES = {"APPROVED", "REJECTED", "PENDING", "DRAFT"}

# Webmail and generic domain blacklist
WEBMAIL_DOMAINS: Set[str] = {
    "gmail.com",
    "yahoo.com",
    "hotmail.com",
    "outlook.com",
    "icloud.com",
    "aol.com",
    "protonmail.com",
    "mail.com",
    "zoho.com",
    "yandex.com",
    "gmx.com",
}

# Legal entity suffixes stripped during conservative company name normalization
LEGAL_ENTITY_SUFFIXES: Set[str] = {
    "inc", "incorporated", "corp", "corporation", "co", "company",
    "ltd", "limited", "llc", "plc", "sa", "bhd", "sdn bhd",
    "gmbh", "ag", "nv", "bv", "spa"
}


def normalize_domain(domain_str: Any) -> str:
    """
    Normalizes a domain string by stripping protocols, www, ports, paths, query params, and casing.
    Returns clean lowercase hostname or empty string.
    """
    if not domain_str or str(domain_str).strip() == "" or str(domain_str).lower() == "nan":
        return ""
    d = str(domain_str).strip().lower()
    d = re.sub(r"^https?://", "", d)
    d = re.sub(r"^www\.", "", d)
    d = d.split("/")[0].split(":")[0].split("?")[0].strip()
    return d


def is_valid_domain(domain_str: str) -> bool:
    """
    Checks if a domain string is syntactically valid:
    must have at least one dot, no whitespace, valid domain characters, and valid labels.
    """
    d = normalize_domain(domain_str)
    if not d or len(d) < 3 or len(d) > 253:
        return False
    if " " in d or "/" in d or "@" in d or ":" in d:
        return False
    parts = d.split(".")
    if len(parts) < 2:
        return False
    for p in parts:
        if not p or len(p) > 63:
            return False
        if p.startswith("-") or p.endswith("-"):
            return False
        if not re.match(r"^[a-z0-9-]+$", p):
            return False
    # TLD must be at least 2 alpha characters
    if not re.match(r"^[a-z]{2,}$", parts[-1]):
        return False
    return True


def is_webmail_or_disposable_domain(domain_str: str) -> bool:
    """
    Checks whether a domain is a known webmail or disposable email service.
    """
    d = normalize_domain(domain_str)
    return d in WEBMAIL_DOMAINS


def normalize_company_name_conservative(name_str: Any) -> str:
    """
    Conservative string normalization for company names:
    lower-cased, removes parenthetical tokens, removes punctuation, strips common legal entity suffixes.
    """
    if not name_str or str(name_str).strip() == "" or str(name_str).lower() == "nan":
        return ""
    s = str(name_str).strip().lower()
    s = re.sub(r"\([^)]*\)", "", s)
    s = re.sub(r"[^\w\s]", " ", s)
    tokens = s.split()
    filtered = [t for t in tokens if t not in LEGAL_ENTITY_SUFFIXES]
    return " ".join(filtered) if filtered else " ".join(tokens)


def normalize_ticker(ticker_str: Any) -> str:
    """
    Normalizes a ticker symbol: strips, removes punctuation, returns lowercase alphanumeric token.
    """
    if not ticker_str or str(ticker_str).strip() == "" or str(ticker_str).lower() == "nan":
        return ""
    t = str(ticker_str).strip().lower()
    t = re.sub(r"[^\w]", "", t)
    return t


def is_valid_ticker(ticker_str: str) -> bool:
    """
    Validates a ticker: 1 to 10 alphanumeric characters, no spaces, not empty.
    """
    t = normalize_ticker(ticker_str)
    if not t or len(t) < 1 or len(t) > 10:
        return False
    return bool(re.match(r"^[a-z0-9]{1,10}$", t))


def extract_parenthetical_tickers(name_str: str) -> Set[str]:
    """
    Extracts explicit parenthetical ticker tokens from a company name string,
    e.g. 'Reliance (RIL)' -> {'ril'}.
    Compares complete normalized tokens, never substrings.
    """
    if not name_str:
        return set()
    matches = re.findall(r"\(([A-Za-z0-9&.\-_/]+)\)", str(name_str))
    tokens = set()
    for m in matches:
        norm_t = normalize_ticker(m)
        if norm_t:
            tokens.add(norm_t)
    return tokens


def parse_approval_timestamp(ts_val: Any) -> Optional[datetime]:
    """
    Parses an ISO 8601 or YYYY-MM-DD timestamp.
    Returns datetime object or None if invalid.
    """
    if not ts_val or str(ts_val).strip() == "" or str(ts_val).lower() == "nan":
        return None
    s = str(ts_val).strip()
    # Try ISO format
    try:
        if s.endswith("Z"):
            s_iso = s[:-1] + "+00:00"
            return datetime.fromisoformat(s_iso)
        return datetime.fromisoformat(s)
    except Exception:
        pass
    # Try common formats
    for fmt in ("%Y-%m-%d", "%Y-%m-%d %H:%M:%S", "%Y/%m/%d"):
        try:
            return datetime.strptime(s, fmt)
        except Exception:
            pass
    return None


class AccountIdentityRegistry:
    """
    Immutable, validated in-memory identity registry for authorized account resolution.
    Encapsulates canonical mappings, approved aliases, approved domains, and approved tickers.
    Provides fast lookup indexes and strict full-field matching primitives.
    """

    def __init__(
        self,
        canonical_id_to_name: Dict[str, str],
        canonical_name_to_id: Dict[str, str],
        approved_aliases_by_account: Dict[str, List[Dict[str, Any]]],
        approved_domains_by_account: Dict[str, List[Dict[str, Any]]],
        approved_tickers_by_account: Dict[str, List[Dict[str, Any]]],
        alias_index: Dict[str, Dict[str, Any]],
        domain_index: Dict[str, Dict[str, Any]],
        ticker_index: Dict[str, Dict[str, Any]],
        quarantined_rows: Optional[List[Dict[str, Any]]] = None,
        quarantine_reasons: Optional[List[str]] = None,
    ):
        self._id_to_name = dict(canonical_id_to_name)
        self._name_to_id = dict(canonical_name_to_id)
        self._aliases = {k: list(v) for k, v in approved_aliases_by_account.items()}
        self._domains = {k: list(v) for k, v in approved_domains_by_account.items()}
        self._tickers = {k: list(v) for k, v in approved_tickers_by_account.items()}
        self._alias_index = dict(alias_index)
        self._domain_index = dict(domain_index)
        self._ticker_index = dict(ticker_index)
        self._quarantined_rows = list(quarantined_rows or [])
        self._quarantine_reasons = list(quarantine_reasons or [])

    @property
    def accounts(self) -> Set[str]:
        return set(self._id_to_name.keys())

    @property
    def approved_account_count(self) -> int:
        return len(self._id_to_name)

    @property
    def account_count(self) -> int:
        return len(self._id_to_name)

    @property
    def quarantined_rows(self) -> List[Dict[str, Any]]:
        return list(self._quarantined_rows)

    @property
    def quarantine_reasons(self) -> List[str]:
        return list(self._quarantine_reasons)

    def get_canonical_name(self, account_id: str) -> Optional[str]:
        return self._id_to_name.get(account_id)

    def get_canonical_id(self, company_name: str) -> Optional[str]:
        return self._name_to_id.get(company_name)

    def get_approved_aliases(self, account_id: str) -> List[str]:
        return [entry["raw_value"] for entry in self._aliases.get(account_id, [])]

    def get_approved_domains(self, account_id: str) -> List[str]:
        return [entry["raw_value"] for entry in self._domains.get(account_id, [])]

    def get_approved_tickers(self, account_id: str) -> List[str]:
        return [entry["raw_value"] for entry in self._tickers.get(account_id, [])]

    def get_account_approved_names(self, account_id: str) -> Set[str]:
        """Returns normalized canonical name and all normalized approved aliases for this account."""
        res: Set[str] = set()
        c_name = self._id_to_name.get(account_id)
        if c_name:
            res.add(normalize_company_name_conservative(c_name))
            res.add(c_name.strip().lower())
        for entry in self._aliases.get(account_id, []):
            res.add(entry["norm_value"])
            res.add(entry["raw_value"].strip().lower())
        return res

    def get_account_approved_domains(self, account_id: str) -> Set[str]:
        """Returns all normalized approved domains for this account."""
        return {entry["norm_value"] for entry in self._domains.get(account_id, [])}

    def get_account_approved_tickers(self, account_id: str) -> Set[str]:
        """Returns all normalized approved tickers for this account."""
        return {entry["norm_value"] for entry in self._tickers.get(account_id, [])}

    def resolve_alias(self, raw_or_norm_alias: str) -> Optional[Dict[str, Any]]:
        norm = normalize_company_name_conservative(raw_or_norm_alias)
        return self._alias_index.get(norm)

    def resolve_domain(self, domain_str: str) -> Optional[Dict[str, Any]]:
        norm = normalize_domain(domain_str)
        return self._domain_index.get(norm)

    def resolve_ticker(self, ticker_str: str) -> Optional[Dict[str, Any]]:
        norm = normalize_ticker(ticker_str)
        return self._ticker_index.get(norm)


def parse_identity_crosswalk(file_or_content: Any) -> Dict[str, Any]:
    """
    Parses and validates an Account Identity Crosswalk CSV.
    Enforces:
      1. Schema validation: required columns must be present; no duplicate column names.
         Harmless additional columns are allowed.
      2. Encoding / decode error safety.
      3. Supported status vocabulary: APPROVED, REJECTED, PENDING, DRAFT (case-insensitive).
         Unrecognized status values produce a fatal complete-file validation error.
      4. Canonical ID and name consistency across rows.
      5. Normalized collision detection across canonical accounts:
         - Normalized alias collision -> fatal complete-file error
         - Normalized domain collision -> fatal complete-file error
         - Normalized ticker collision -> fatal complete-file error
      6. If fatal errors exist, file_is_valid=False, registry_applied=False, registry=None.
         No row may be applied when a fatal complete-file error exists.
      7. Only after complete-file validation succeeds, quarantine non-ambiguous individual rows:
         - Missing required row metadata (id, name, status, approver, timestamp)
         - Status other than APPROVED
         - No populated identity value (alias, domain, ticker all empty)
         - Malformed domain / generic / webmail domain
         - Malformed ticker / alias
         - Invalid approval timestamp
      8. Build immutable AccountIdentityRegistry from approved valid rows.
    """
    fatal_errors: List[str] = []
    quarantined_rows: List[Dict[str, Any]] = []
    quarantine_reasons: List[str] = []
    normalized_collisions: List[str] = []

    content_str = ""
    try:
        if hasattr(file_or_content, "read"):
            raw = file_or_content.read()
        elif isinstance(file_or_content, Path):
            with open(file_or_content, "r", encoding="utf-8-sig", errors="replace") as f:
                content_str = f.read()
        elif isinstance(file_or_content, str):
            if "\n" not in file_or_content and len(file_or_content) < 260 and Path(file_or_content).exists() and Path(file_or_content).is_file():
                with open(file_or_content, "r", encoding="utf-8-sig", errors="replace") as f:
                    content_str = f.read()
            else:
                content_str = file_or_content
        elif isinstance(file_or_content, bytes):
            content_str = file_or_content.decode("utf-8-sig", errors="replace")
        else:
            return {
                "file_is_valid": False,
                "registry_applied": False,
                "fatal_errors": ["Unable to read file input: unsupported input type."],
                "approved_rows": [],
                "quarantined_rows": [],
                "quarantine_reasons": [],
                "normalized_collisions": [],
                "registry": None,
            }
    except Exception as e:
        return {
            "file_is_valid": False,
            "registry_applied": False,
            "fatal_errors": [f"File decoding or reading error: {str(e)}"],
            "approved_rows": [],
            "quarantined_rows": [],
            "quarantine_reasons": [],
            "normalized_collisions": [],
            "registry": None,
        }

    if not content_str.strip():
        return {
            "file_is_valid": False,
            "registry_applied": False,
            "fatal_errors": ["Crosswalk CSV file is empty."],
            "approved_rows": [],
            "quarantined_rows": [],
            "quarantine_reasons": [],
            "normalized_collisions": [],
            "registry": None,
        }

    reader = csv.reader(io.StringIO(content_str))
    try:
        raw_header = next(reader, None)
    except Exception as e:
        return {
            "file_is_valid": False,
            "registry_applied": False,
            "fatal_errors": [f"CSV parse error in header: {str(e)}"],
            "approved_rows": [],
            "quarantined_rows": [],
            "quarantine_reasons": [],
            "normalized_collisions": [],
            "registry": None,
        }

    if not raw_header:
        return {
            "file_is_valid": False,
            "registry_applied": False,
            "fatal_errors": ["Crosswalk CSV contains no header row."],
            "approved_rows": [],
            "quarantined_rows": [],
            "quarantine_reasons": [],
            "normalized_collisions": [],
            "registry": None,
        }

    clean_header = [c.strip() for c in raw_header]
    header_lower = [c.lower() for c in clean_header]

    seen_headers = set()
    for col in header_lower:
        if col in seen_headers:
            fatal_errors.append(f"Duplicate column name '{col}' in crosswalk CSV.")
        seen_headers.add(col)

    for req in REQUIRED_CROSSWALK_COLUMNS:
        if req.lower() not in seen_headers:
            fatal_errors.append(f"Missing required crosswalk column: '{req}'.")

    if fatal_errors:
        return {
            "file_is_valid": False,
            "registry_applied": False,
            "fatal_errors": fatal_errors,
            "approved_rows": [],
            "quarantined_rows": [],
            "quarantine_reasons": [],
            "normalized_collisions": [],
            "registry": None,
        }

    col_idx = {col.lower(): i for i, col in enumerate(clean_header)}

    raw_rows = []
    line_num = 1
    for row in reader:
        line_num += 1
        if not row or not any(field.strip() for field in row):
            continue
        row_dict: Dict[str, Any] = {"_row_num": line_num}
        for col_name, idx in col_idx.items():
            row_dict[col_name] = row[idx].strip() if idx < len(row) else ""
        raw_rows.append(row_dict)

    if not raw_rows:
        return {
            "file_is_valid": False,
            "registry_applied": False,
            "fatal_errors": ["Crosswalk CSV contains header but no data rows."],
            "approved_rows": [],
            "quarantined_rows": [],
            "quarantine_reasons": [],
            "normalized_collisions": [],
            "registry": None,
        }

    # Step 2: Validate status vocabulary across all rows (Fatal check)
    for r in raw_rows:
        status_val = r.get("approval_status", "").strip().upper()
        if status_val and status_val not in SUPPORTED_STATUSES:
            fatal_errors.append(
                f"Row {r['_row_num']}: Unrecognized approval_status value '{r.get('approval_status')}'. "
                f"Must be one of {sorted(list(SUPPORTED_STATUSES))}."
            )

    # Step 3: Check canonical ID & Name consistency (Fatal check)
    id_to_name_map: Dict[str, str] = {}
    name_to_id_map: Dict[str, str] = {}

    for r in raw_rows:
        c_id = r.get("canonical_account_id", "").strip()
        c_name = r.get("canonical_company_name", "").strip()
        if not c_id or not c_name:
            continue
        if c_id in id_to_name_map:
            if id_to_name_map[c_id].lower() != c_name.lower():
                fatal_errors.append(
                    f"Conflicting canonical name mapping for account ID '{c_id}': "
                    f"mapped to both '{id_to_name_map[c_id]}' and '{c_name}'."
                )
        else:
            id_to_name_map[c_id] = c_name

        norm_c_name = normalize_company_name_conservative(c_name)
        if norm_c_name in name_to_id_map:
            if name_to_id_map[norm_c_name] != c_id:
                fatal_errors.append(
                    f"Conflicting canonical ID mapping for company '{c_name}': "
                    f"mapped to both account ID '{name_to_id_map[norm_c_name]}' and '{c_id}'."
                )
        else:
            name_to_id_map[norm_c_name] = c_id

    # Step 4: Collision detection across canonical accounts (Fatal checks)
    alias_ownership: Dict[str, Dict[str, Any]] = {}
    domain_ownership: Dict[str, Dict[str, Any]] = {}
    ticker_ownership: Dict[str, Dict[str, Any]] = {}

    for r in raw_rows:
        c_id = r.get("canonical_account_id", "").strip()
        if not c_id:
            continue

        raw_alias = r.get("approved_alias", "").strip()
        raw_dom = r.get("approved_domain", "").strip()
        raw_tick = r.get("approved_ticker", "").strip()

        if raw_alias:
            norm_a = normalize_company_name_conservative(raw_alias)
            if norm_a:
                if norm_a in alias_ownership:
                    prev = alias_ownership[norm_a]
                    if prev["account_id"] != c_id:
                        msg = (
                            f"Normalized alias collision: '{norm_a}' maps to multiple canonical accounts "
                            f"('{prev['account_id']}' on row {prev['row_num']} and '{c_id}' on row {r['_row_num']})."
                        )
                        fatal_errors.append(msg)
                        normalized_collisions.append(msg)
                else:
                    alias_ownership[norm_a] = {"account_id": c_id, "row_num": r["_row_num"]}

        if raw_dom:
            norm_d = normalize_domain(raw_dom)
            if norm_d:
                if norm_d in domain_ownership:
                    prev = domain_ownership[norm_d]
                    if prev["account_id"] != c_id:
                        msg = (
                            f"Normalized domain collision: '{norm_d}' maps to multiple canonical accounts "
                            f"('{prev['account_id']}' on row {prev['row_num']} and '{c_id}' on row {r['_row_num']})."
                        )
                        fatal_errors.append(msg)
                        normalized_collisions.append(msg)
                else:
                    domain_ownership[norm_d] = {"account_id": c_id, "row_num": r["_row_num"]}

        if raw_tick:
            norm_t = normalize_ticker(raw_tick)
            if norm_t:
                if norm_t in ticker_ownership:
                    prev = ticker_ownership[norm_t]
                    if prev["account_id"] != c_id:
                        msg = (
                            f"Normalized ticker collision: '{norm_t}' maps to multiple canonical accounts "
                            f"('{prev['account_id']}' on row {prev['row_num']} and '{c_id}' on row {r['_row_num']})."
                        )
                        fatal_errors.append(msg)
                        normalized_collisions.append(msg)
                else:
                    ticker_ownership[norm_t] = {"account_id": c_id, "row_num": r["_row_num"]}

    if fatal_errors:
        return {
            "file_is_valid": False,
            "registry_applied": False,
            "fatal_errors": fatal_errors,
            "approved_rows": [],
            "quarantined_rows": [],
            "quarantine_reasons": [],
            "normalized_collisions": normalized_collisions,
            "registry": None,
        }

    # Step 5: Safe Row Quarantine (Only after complete-file checks pass!)
    approved_rows: List[Dict[str, Any]] = []

    for r in raw_rows:
        row_num = r["_row_num"]
        c_id = r.get("canonical_account_id", "").strip()
        c_name = r.get("canonical_company_name", "").strip()
        status = r.get("approval_status", "").strip().upper()
        approver = r.get("approved_by", "").strip()
        ts_val = r.get("approved_at", "").strip()
        raw_alias = r.get("approved_alias", "").strip()
        raw_dom = r.get("approved_domain", "").strip()
        raw_tick = r.get("approved_ticker", "").strip()

        row_reasons = []

        if not c_id:
            row_reasons.append(f"Row {row_num}: Missing canonical_account_id.")
        if not c_name:
            row_reasons.append(f"Row {row_num}: Missing canonical_company_name.")
        if not status:
            row_reasons.append(f"Row {row_num}: Missing approval_status.")
        elif status != "APPROVED":
            row_reasons.append(f"Row {row_num}: Status is '{status}' (only APPROVED authorizes matching).")
        if not approver:
            row_reasons.append(f"Row {row_num}: Missing approved_by.")
        if not ts_val:
            row_reasons.append(f"Row {row_num}: Missing approved_at timestamp.")
        else:
            parsed_ts = parse_approval_timestamp(ts_val)
            if not parsed_ts:
                row_reasons.append(f"Row {row_num}: Malformed approved_at timestamp '{ts_val}'.")

        if not raw_alias and not raw_dom and not raw_tick:
            row_reasons.append(f"Row {row_num}: No alias, domain, or ticker value populated.")

        if raw_dom:
            norm_d = normalize_domain(raw_dom)
            if not is_valid_domain(norm_d):
                row_reasons.append(f"Row {row_num}: Malformed domain '{raw_dom}'.")
            elif is_webmail_or_disposable_domain(norm_d):
                row_reasons.append(f"Row {row_num}: Prohibited webmail/generic domain '{norm_d}'.")

        if raw_tick:
            if not is_valid_ticker(raw_tick):
                row_reasons.append(f"Row {row_num}: Malformed ticker '{raw_tick}'.")

        if raw_alias:
            if len(raw_alias.strip()) > 150:
                row_reasons.append(f"Row {row_num}: Malformed alias (exceeds 150 characters).")

        if row_reasons:
            quarantined_rows.append(r)
            quarantine_reasons.extend(row_reasons)
        else:
            clean_entry = {
                "canonical_account_id": c_id,
                "canonical_company_name": c_name,
                "approved_alias": raw_alias,
                "approved_domain": normalize_domain(raw_dom) if raw_dom else "",
                "approved_ticker": normalize_ticker(raw_tick) if raw_tick else "",
                "approval_status": "APPROVED",
                "approved_by": approver,
                "approved_at": ts_val,
                "_row_num": row_num,
            }
            approved_rows.append(clean_entry)

    # Step 6: Construct AccountIdentityRegistry
    if not approved_rows:
        return {
            "file_is_valid": True,
            "registry_applied": False,
            "fatal_errors": [],
            "approved_rows": [],
            "quarantined_rows": quarantined_rows,
            "quarantine_reasons": quarantine_reasons,
            "normalized_collisions": [],
            "registry": AccountIdentityRegistry({}, {}, {}, {}, {}, {}, {}, {}, quarantined_rows, quarantine_reasons),
        }

    canonical_id_to_name: Dict[str, str] = {}
    canonical_name_to_id: Dict[str, str] = {}
    approved_aliases_by_account: Dict[str, List[Dict[str, Any]]] = {}
    approved_domains_by_account: Dict[str, List[Dict[str, Any]]] = {}
    approved_tickers_by_account: Dict[str, List[Dict[str, Any]]] = {}
    alias_index: Dict[str, Dict[str, Any]] = {}
    domain_index: Dict[str, Dict[str, Any]] = {}
    ticker_index: Dict[str, Dict[str, Any]] = {}

    for row in approved_rows:
        acc_id = row["canonical_account_id"]
        acc_name = row["canonical_company_name"]
        canonical_id_to_name[acc_id] = acc_name
        canonical_name_to_id[acc_name] = acc_id

        meta = {
            "canonical_account_id": acc_id,
            "canonical_company_name": acc_name,
            "approval_status": "APPROVED",
            "approved_by": row["approved_by"],
            "approved_at": row["approved_at"],
            "row_num": row["_row_num"],
        }

        if row["approved_alias"]:
            norm_a = normalize_company_name_conservative(row["approved_alias"])
            entry = {**meta, "raw_value": row["approved_alias"], "norm_value": norm_a}
            approved_aliases_by_account.setdefault(acc_id, []).append(entry)
            alias_index[norm_a] = entry

        if row["approved_domain"]:
            norm_d = row["approved_domain"]
            entry = {**meta, "raw_value": norm_d, "norm_value": norm_d}
            approved_domains_by_account.setdefault(acc_id, []).append(entry)
            domain_index[norm_d] = entry

        if row["approved_ticker"]:
            norm_t = row["approved_ticker"]
            entry = {**meta, "raw_value": norm_t, "norm_value": norm_t}
            approved_tickers_by_account.setdefault(acc_id, []).append(entry)
            ticker_index[norm_t] = entry

    registry = AccountIdentityRegistry(
        canonical_id_to_name=canonical_id_to_name,
        canonical_name_to_id=canonical_name_to_id,
        approved_aliases_by_account=approved_aliases_by_account,
        approved_domains_by_account=approved_domains_by_account,
        approved_tickers_by_account=approved_tickers_by_account,
        alias_index=alias_index,
        domain_index=domain_index,
        ticker_index=ticker_index,
        quarantined_rows=quarantined_rows,
        quarantine_reasons=quarantine_reasons,
    )

    return {
        "file_is_valid": True,
        "registry_applied": True,
        "fatal_errors": [],
        "approved_rows": approved_rows,
        "quarantined_rows": quarantined_rows,
        "quarantine_reasons": quarantine_reasons,
        "normalized_collisions": [],
        "registry": registry,
    }


def match_source_record_identity(
    candidate_company: str,
    candidate_domain: str,
    canonical_account_id: str,
    canonical_company_name: str,
    identity_registry: Optional[AccountIdentityRegistry] = None,
    allow_unapproved_domain_proposal: bool = False,
) -> Dict[str, Any]:
    """
    Core shared entity-resolution matcher for Wingman, CRM, and Contact ingestion.
    Strictly prohibits substring containment.
    Allowed routes:
      1. NORMALIZED_CANONICAL_NAME (always permitted if exact full-field equality)
      2. APPROVED_ALIAS (full-field equality with approved alias from registry)
      3. APPROVED_DOMAIN (exact equality with approved non-webmail domain from registry)
      4. APPROVED_TICKER (exact whole-field equality with approved ticker from registry)
      5. APPROVED_PARENTHETICAL_TICKER (exact parenthetical token match with approved ticker from registry)
    """
    rec_comp_raw = str(candidate_company or "").strip().lower()
    rec_comp_norm = normalize_company_name_conservative(candidate_company)
    rec_dom = normalize_domain(candidate_domain)
    target_clean_name = normalize_company_name_conservative(canonical_company_name)
    target_raw_lower = canonical_company_name.strip().lower()

    route_canonical = False
    if target_clean_name and rec_comp_norm and target_clean_name == rec_comp_norm:
        route_canonical = True
    elif target_raw_lower and rec_comp_raw and target_raw_lower == rec_comp_raw:
        route_canonical = True

    routes_satisfied: List[str] = []
    matched_vals: Dict[str, str] = {}
    matched_lineage: Dict[str, Any] = {
        "canonical_account_id": canonical_account_id,
        "canonical_company_name": canonical_company_name,
        "registry_source": "EXACT_CANONICAL" if route_canonical else "NONE",
        "registry_approval_status": "CANONICAL_NAME_FALLBACK" if route_canonical else "NONE",
        "registry_approved_by": "SYSTEM_CANONICAL_RULE" if route_canonical else "NONE",
        "registry_approved_at": datetime.now().date().isoformat() if route_canonical else "NONE",
    }

    if route_canonical:
        routes_satisfied.append("NORMALIZED_CANONICAL_NAME")
        matched_vals["NORMALIZED_CANONICAL_NAME"] = target_clean_name

    if identity_registry:
        approved_names = identity_registry.get_account_approved_names(canonical_account_id)
        approved_domains = identity_registry.get_account_approved_domains(canonical_account_id)
        approved_tickers = identity_registry.get_account_approved_tickers(canonical_account_id)

        # Route 2: Approved Alias (FULL-FIELD ONLY, NEVER SUBSTRING)
        for a_norm in approved_names:
            if a_norm and (rec_comp_norm == a_norm or rec_comp_raw == a_norm):
                alias_meta = identity_registry.resolve_alias(a_norm)
                routes_satisfied.append("APPROVED_ALIAS")
                matched_vals["APPROVED_ALIAS"] = a_norm
                if alias_meta:
                    matched_lineage["registry_source"] = "REGISTRY"
                    matched_lineage["registry_approval_status"] = alias_meta.get("approval_status", "APPROVED")
                    matched_lineage["registry_approved_by"] = alias_meta.get("approved_by", "REGISTRY")
                    matched_lineage["registry_approved_at"] = alias_meta.get("approved_at", "REGISTRY")
                break

        # Route 3: Approved Domain
        if rec_dom and rec_dom in approved_domains and not is_webmail_or_disposable_domain(rec_dom):
            dom_meta = identity_registry.resolve_domain(rec_dom)
            routes_satisfied.append("APPROVED_DOMAIN")
            matched_vals["APPROVED_DOMAIN"] = rec_dom
            if dom_meta:
                matched_lineage["registry_source"] = "REGISTRY"
                matched_lineage["registry_approval_status"] = dom_meta.get("approval_status", "APPROVED")
                matched_lineage["registry_approved_by"] = dom_meta.get("approved_by", "REGISTRY")
                matched_lineage["registry_approved_at"] = dom_meta.get("approved_at", "REGISTRY")

        # Route 4: Approved Ticker / Route 5: Approved Parenthetical Ticker
        paren_tokens = extract_parenthetical_tickers(candidate_company)
        for t_val in approved_tickers:
            if rec_comp_norm == t_val or rec_comp_raw == t_val:
                t_meta = identity_registry.resolve_ticker(t_val)
                routes_satisfied.append("APPROVED_TICKER")
                matched_vals["APPROVED_TICKER"] = t_val
                if t_meta:
                    matched_lineage["registry_source"] = "REGISTRY"
                    matched_lineage["registry_approval_status"] = t_meta.get("approval_status", "APPROVED")
                    matched_lineage["registry_approved_by"] = t_meta.get("approved_by", "REGISTRY")
                    matched_lineage["registry_approved_at"] = t_meta.get("approved_at", "REGISTRY")
                break
            elif t_val in paren_tokens:
                t_meta = identity_registry.resolve_ticker(t_val)
                routes_satisfied.append("APPROVED_PARENTHETICAL_TICKER")
                matched_vals["APPROVED_PARENTHETICAL_TICKER"] = t_val
                if t_meta:
                    matched_lineage["registry_source"] = "REGISTRY"
                    matched_lineage["registry_approval_status"] = t_meta.get("approval_status", "APPROVED")
                    matched_lineage["registry_approved_by"] = t_meta.get("approved_by", "REGISTRY")
                    matched_lineage["registry_approved_at"] = t_meta.get("approved_at", "REGISTRY")
                break

    if routes_satisfied:
        primary_route = routes_satisfied[0]
        primary_val = matched_vals[primary_route]
        conf = "HIGH" if primary_route in ("NORMALIZED_CANONICAL_NAME", "APPROVED_DOMAIN", "APPROVED_ALIAS", "APPROVED_TICKER", "APPROVED_PARENTHETICAL_TICKER") else "MEDIUM"
        return {
            "matched": True,
            "route": primary_route,
            "all_routes": routes_satisfied,
            "matched_value": primary_val,
            "confidence": conf,
            "lineage": matched_lineage,
            "is_proposed_association": False,
            "review_required": False,
        }

    if allow_unapproved_domain_proposal and rec_dom and not is_webmail_or_disposable_domain(rec_dom):
        return {
            "matched": False,
            "route": "PROPOSED_ASSOCIATION",
            "all_routes": ["PROPOSED_ASSOCIATION"],
            "matched_value": rec_dom,
            "confidence": "NONE",
            "lineage": {
                "canonical_account_id": canonical_account_id,
                "canonical_company_name": canonical_company_name,
                "registry_source": "EXPORT_PROPOSAL",
                "registry_approval_status": "UNAPPROVED_PROPOSAL",
                "registry_approved_by": "NONE",
                "registry_approved_at": "NONE",
            },
            "is_proposed_association": True,
            "review_required": True,
        }

    return {
        "matched": False,
        "route": None,
        "all_routes": [],
        "matched_value": "",
        "confidence": "NONE",
        "lineage": {
            "canonical_account_id": canonical_account_id,
            "canonical_company_name": canonical_company_name,
            "registry_source": "NONE",
            "registry_approval_status": "NONE",
            "registry_approved_by": "NONE",
            "registry_approved_at": "NONE",
        },
        "is_proposed_association": False,
        "review_required": False,
    }


def assert_account_match_integrity(
    canonical_account_id: str,
    matched_records: List[Dict[str, Any]],
    allowed_normalized_names: Optional[Set[str]] = None,
    allowed_raw_names: Optional[Set[str]] = None,
    allowed_tickers: Optional[Set[str]] = None,
    verified_domain: Optional[str] = None,
    canonical_company_name: Optional[str] = None,
    identity_registry: Optional[AccountIdentityRegistry] = None,
) -> None:
    """
    Pre-scoring integrity assertion.
    Asserts that EVERY matched record admitted to scoring satisfies an approved route
    or permitted exact canonical-name route.
    Accepts either explicit allowed sets or an AccountIdentityRegistry.
    """
    clean_norm_names: Set[str] = set(allowed_normalized_names or [])
    clean_raw_names: Set[str] = set(allowed_raw_names or [])
    clean_tickers: Set[str] = set(allowed_tickers or [])

    if canonical_company_name:
        clean_norm_names.add(normalize_company_name_conservative(canonical_company_name))
        clean_raw_names.add(canonical_company_name.strip().lower())

    if identity_registry:
        clean_norm_names |= identity_registry.get_account_approved_names(canonical_account_id)
        clean_tickers |= identity_registry.get_account_approved_tickers(canonical_account_id)
        approved_doms = identity_registry.get_account_approved_domains(canonical_account_id)
    else:
        approved_doms = {verified_domain.lower()} if verified_domain else set()

    for rec in matched_records:
        rec_comp = rec.get("company", "")
        rec_comp_raw = str(rec_comp).strip().lower()
        rec_comp_norm = normalize_company_name_conservative(rec_comp)
        rec_dom = normalize_domain(rec.get("domain", ""))
        paren_tokens = extract_parenthetical_tickers(rec_comp)

        name_ok = (rec_comp_norm in clean_norm_names) or (rec_comp_raw in clean_raw_names)
        dom_ok = bool(rec_dom and rec_dom in approved_doms and not is_webmail_or_disposable_domain(rec_dom))
        ticker_ok = bool(
            clean_tickers
            and ((rec_comp_norm in clean_tickers) or (rec_comp_raw in clean_tickers) or bool(paren_tokens & clean_tickers))
        )

        if not (name_ok or dom_ok or ticker_ok):
            raise AssertionError(
                f"Account-match integrity assertion failed for canonical account '{canonical_account_id}': "
                f"Record '{rec_comp}' (domain: '{rec_dom}') does not satisfy any approved route "
                f"(allowed names: {clean_norm_names | clean_raw_names}, allowed tickers: {clean_tickers}, "
                f"approved domains: {approved_doms})."
            )
