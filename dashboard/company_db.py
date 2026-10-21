"""
Company Database & Master Store Module (Phase 4 Foundation)
EON Commercial Intelligence | External Review Build

Provides DB-first company management:
- SQLite embedded database as default system of record (2,000+ company scale)
- Tables: companies, company_triggers, company_enrichment_status, company_field_provenance, enrichment_raw_cache
- Direct single-company creation without CSV upload
- CSV import/update/override mechanism (CSV as secondary import, not primary truth)
- Granular field-level provenance tracking: source URL, source type, source date, confidence, exact/range/estimate/unknown status
- Enrichment lifecycle status: not_started, partial, complete, stale, failed
- Thread-safe connection handling and WAL mode enabled
"""

import datetime
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import threading
from typing import Any, Dict, List, Optional, Tuple, Union

import pandas as pd

# Default Database Path
DEFAULT_DB_PATH = Path(__file__).resolve().parents[1] / "local_data" / "companies_master.db"

# Thread-local storage for SQLite connections
_thread_local = threading.local()

ENRICHMENT_STATUSES = {"not_started", "partial", "complete", "stale", "failed"}
VALUE_STATUSES = {"exact", "range", "estimate", "unknown"}
SOURCE_TYPES = {"sec_edgar", "wikidata", "first_party", "user_direct", "csv_import", "none"}
CONFIDENCE_TIERS = {"HIGH", "MEDIUM", "LOW", "UNVERIFIED"}
DEFAULT_STALE_DAYS = 90


def get_db_connection(db_path: Optional[Union[str, Path]] = None) -> sqlite3.Connection:
    """
    Returns a thread-safe connection to the SQLite database.
    Configures WAL mode and row factory for dictionary-like access.
    
    Concurrency note: SQLite WAL improves concurrency substantially by allowing
    concurrent readers alongside an active writer without reader-writer blocking.
    However, write transactions remain strictly serialized, so concurrent writers
    will wait up to busy_timeout (30.0s) before raising a locked error.
    """
    path = str(db_path or DEFAULT_DB_PATH)
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)

    conn = sqlite3.connect(path, timeout=30.0, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    # Enable Write-Ahead Logging for high reader concurrency
    conn.execute("PRAGMA journal_mode = WAL;")
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.execute("PRAGMA synchronous = NORMAL;")
    return conn


def init_company_database(db_path: Optional[Union[str, Path]] = None) -> None:
    """
    Initializes the database schema with necessary tables, indexes, and constraints.
    Safe to call multiple times (idempotent).
    """
    conn = get_db_connection(db_path)
    with conn:
        # 1. Master Companies Universe Table
        conn.execute("""
            CREATE TABLE IF NOT EXISTS companies (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                company_id TEXT UNIQUE NOT NULL,
                company_name TEXT NOT NULL,
                normalized_name TEXT NOT NULL,
                domain TEXT,
                normalized_domain TEXT,
                segment TEXT NOT NULL,
                source_tier INTEGER DEFAULT 3,
                created_source TEXT NOT NULL CHECK(created_source IN ('db_seed', 'user_direct', 'csv_import')),
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_companies_norm_name ON companies(normalized_name);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_companies_norm_domain ON companies(normalized_domain);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_companies_segment ON companies(segment);")

        # 2. Company Triggers / Catalysts Table
        conn.execute("""
            CREATE TABLE IF NOT EXISTS company_triggers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                company_id TEXT NOT NULL REFERENCES companies(company_id) ON DELETE CASCADE,
                trigger_type TEXT,
                trigger_date TEXT,
                trigger_summary TEXT,
                trigger_source_url TEXT,
                scanned_at TEXT,
                source TEXT NOT NULL DEFAULT 'default_seed'
            );
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_triggers_company_id ON company_triggers(company_id);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_triggers_type ON company_triggers(trigger_type);")

        # 3. Company Enrichment Status Table
        conn.execute("""
            CREATE TABLE IF NOT EXISTS company_enrichment_status (
                company_id TEXT PRIMARY KEY REFERENCES companies(company_id) ON DELETE CASCADE,
                enrichment_status TEXT NOT NULL CHECK(enrichment_status IN ('not_started', 'partial', 'complete', 'stale', 'failed')),
                priority_tier INTEGER NOT NULL DEFAULT 2, -- 1: Immediate/Top-Ranked, 2: Background Backfill
                last_attempted_at TEXT,
                last_enriched_at TEXT,
                stale_after TEXT,
                fields_enriched_count INTEGER NOT NULL DEFAULT 0,
                fields_unknown_count INTEGER NOT NULL DEFAULT 0,
                error_message TEXT,
                sec_edgar_status TEXT DEFAULT 'not_started',
                wikidata_status TEXT DEFAULT 'not_started'
            );
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_enrichment_status ON company_enrichment_status(enrichment_status);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_enrichment_priority ON company_enrichment_status(priority_tier);")

        # 4. Field-Level Provenance Table (Strict Rule: Every enriched field stores source URL, type, date, confidence, exact/range/estimate/unknown)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS company_field_provenance (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                company_id TEXT NOT NULL REFERENCES companies(company_id) ON DELETE CASCADE,
                field_name TEXT NOT NULL,
                field_value TEXT,
                value_status TEXT NOT NULL CHECK(value_status IN ('exact', 'range', 'estimate', 'unknown')),
                source_url TEXT,
                source_type TEXT NOT NULL CHECK(source_type IN ('sec_edgar', 'wikidata', 'first_party', 'user_direct', 'csv_import', 'none')),
                source_date TEXT,
                confidence TEXT NOT NULL CHECK(confidence IN ('HIGH', 'MEDIUM', 'LOW', 'UNVERIFIED')),
                retrieved_at TEXT NOT NULL,
                is_stale INTEGER NOT NULL DEFAULT 0,
                raw_evidence_snippet TEXT,
                UNIQUE(company_id, field_name)
            );
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_provenance_comp_field ON company_field_provenance(company_id, field_name);")

        # 5. Connector HTTP Cache (to prevent redundant hits to free APIs and respect rate limits)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS enrichment_raw_cache (
                cache_key TEXT PRIMARY KEY,
                source_type TEXT NOT NULL,
                request_url TEXT NOT NULL,
                response_json TEXT NOT NULL,
                http_status INTEGER NOT NULL,
                cached_at TEXT NOT NULL,
                expires_at TEXT NOT NULL
            );
        """)


def normalize_str(s: Any) -> str:
    """Helper to cleanly lowercase and trim strings."""
    if s is None or pd.isna(s):
        return ""
    return str(s).strip().lower()


def generate_company_id(name: str, domain: Optional[str] = None) -> str:
    """Generates a deterministic unique company ID."""
    clean_name = normalize_str(name)
    clean_domain = normalize_str(domain)
    slug = "".join(c if c.isalnum() else "_" for c in clean_name)[:32].strip("_")
    h = hashlib.sha256(f"{clean_name}|{clean_domain}".encode("utf-8")).hexdigest()[:8]
    return f"comp_{slug}_{h}" if slug else f"comp_{h}"


def seed_database_from_default_csv(
    csv_path: Optional[Union[str, Path]] = None,
    db_path: Optional[Union[str, Path]] = None,
    force_reseed: bool = False,
) -> int:
    """
    Populates the database from the default sanitized Wingman dataset if empty.
    Returns the count of seeded companies.
    """
    init_company_database(db_path)
    conn = get_db_connection(db_path)

    with conn:
        existing_count = conn.execute("SELECT COUNT(*) FROM companies").fetchone()[0]
        if existing_count > 0 and not force_reseed:
            return existing_count

        if force_reseed:
            conn.execute("DELETE FROM company_triggers;")
            conn.execute("DELETE FROM company_field_provenance;")
            conn.execute("DELETE FROM company_enrichment_status;")
            conn.execute("DELETE FROM companies;")

        project_root = Path(__file__).resolve().parents[1]
        default_csv = Path(csv_path or (project_root / "data" / "wingman-trigger-export-2026-09-17-sanitized.csv"))

        if not default_csv.exists():
            return 0

        df = pd.read_csv(default_csv)
        now_iso = datetime.now(timezone.utc).isoformat()

        # Group by company to create master company records
        comp_groups = df.groupby("company", as_index=False).first()

        comp_name_to_id: Dict[str, str] = {}

        for _, row in comp_groups.iterrows():
            c_name = str(row["company"]).strip()
            c_domain = str(row.get("domain", "") or "").strip()
            c_seg = str(row.get("segment", "General Industrial") or "General Industrial").strip()
            c_tier = int(row.get("source_tier", 3) if pd.notna(row.get("source_tier")) else 3)
            cid = generate_company_id(c_name, c_domain)
            comp_name_to_id[normalize_str(c_name)] = cid

            conn.execute(
                """
                INSERT OR IGNORE INTO companies (
                    company_id, company_name, normalized_name, domain, normalized_domain,
                    segment, source_tier, created_source, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 'db_seed', ?, ?);
                """,
                (
                    cid,
                    c_name,
                    normalize_str(c_name),
                    c_domain,
                    normalize_str(c_domain),
                    c_seg,
                    c_tier,
                    now_iso,
                    now_iso,
                ),
            )

            # Insert initial status as 'not_started'
            conn.execute(
                """
                INSERT OR IGNORE INTO company_enrichment_status (
                    company_id, enrichment_status, priority_tier, fields_enriched_count,
                    fields_unknown_count, sec_edgar_status, wikidata_status
                ) VALUES (?, 'not_started', 2, 0, 0, 'not_started', 'not_started');
                """,
                (cid,),
            )

        # Insert all triggers
        for _, row in df.iterrows():
            c_name = str(row["company"]).strip()
            cid = comp_name_to_id.get(normalize_str(c_name))
            if not cid:
                c_domain = str(row.get("domain", "") or "").strip()
                cid = generate_company_id(c_name, c_domain)

            t_type = str(row.get("trigger_type", "") or "").strip()
            t_date = str(row.get("trigger_date", "") or "").strip()
            t_sum = str(row.get("trigger_summary", "") or "").strip()
            t_url = str(row.get("trigger_source_url", "") or "").strip()
            t_scan = str(row.get("scanned_at", "") or "").strip()

            if t_type or t_sum:
                conn.execute(
                    """
                    INSERT INTO company_triggers (
                        company_id, trigger_type, trigger_date, trigger_summary,
                        trigger_source_url, scanned_at, source
                    ) VALUES (?, ?, ?, ?, ?, ?, 'default_seed');
                    """,
                    (cid, t_type, t_date, t_sum, t_url, t_scan),
                )

        count = conn.execute("SELECT COUNT(*) FROM companies").fetchone()[0]
        return count


def add_single_company(
    company_name: str,
    segment: str,
    domain: Optional[str] = None,
    source_tier: int = 3,
    initial_trigger: Optional[Dict[str, Any]] = None,
    db_path: Optional[Union[str, Path]] = None,
) -> Dict[str, Any]:
    """
    Directly adds a single company to the database without requiring a CSV upload.
    Assigns enrichment status 'not_started' with priority_tier 1 (immediate enrichment).
    Returns created company dictionary.
    """
    init_company_database(db_path)
    conn = get_db_connection(db_path)

    clean_name = str(company_name).strip()
    if not clean_name:
        raise ValueError("company_name cannot be blank.")

    clean_seg = str(segment or "General Industrial").strip()
    clean_domain = str(domain or "").strip()
    cid = generate_company_id(clean_name, clean_domain)
    now_iso = datetime.now(timezone.utc).isoformat()

    with conn:
        # Check if company already exists
        existing = conn.execute(
            "SELECT company_id, company_name FROM companies WHERE company_id = ? OR normalized_name = ?",
            (cid, normalize_str(clean_name)),
        ).fetchone()

        if existing:
            return {
                "success": False,
                "message": f"Company '{existing['company_name']}' already exists in database.",
                "company_id": existing["company_id"],
                "created": False,
            }

        conn.execute(
            """
            INSERT INTO companies (
                company_id, company_name, normalized_name, domain, normalized_domain,
                segment, source_tier, created_source, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, 'user_direct', ?, ?);
            """,
            (
                cid,
                clean_name,
                normalize_str(clean_name),
                clean_domain,
                normalize_str(clean_domain),
                clean_seg,
                int(source_tier),
                now_iso,
                now_iso,
            ),
        )

        # Initial status is 'not_started' with priority_tier 1 (Immediate enrichment priority)
        conn.execute(
            """
            INSERT INTO company_enrichment_status (
                company_id, enrichment_status, priority_tier, fields_enriched_count,
                fields_unknown_count, sec_edgar_status, wikidata_status
            ) VALUES (?, 'not_started', 1, 0, 0, 'not_started', 'not_started');
            """,
            (cid,),
        )

        if initial_trigger:
            conn.execute(
                """
                INSERT INTO company_triggers (
                    company_id, trigger_type, trigger_date, trigger_summary,
                    trigger_source_url, scanned_at, source
                ) VALUES (?, ?, ?, ?, ?, ?, 'user_direct');
                """,
                (
                    cid,
                    str(initial_trigger.get("trigger_type", "") or ""),
                    str(initial_trigger.get("trigger_date", "") or ""),
                    str(initial_trigger.get("trigger_summary", "") or ""),
                    str(initial_trigger.get("trigger_source_url", "") or ""),
                    now_iso[:10],
                ),
            )

    return {
        "success": True,
        "message": f"Company '{clean_name}' successfully created.",
        "company_id": cid,
        "created": True,
        "company_name": clean_name,
        "segment": clean_seg,
        "domain": clean_domain,
    }


def import_csv_as_override(
    df: pd.DataFrame,
    override_mode: str = "merge_update",
    db_path: Optional[Union[str, Path]] = None,
) -> Dict[str, Any]:
    """
    Imports custom CSV rows into the master database.
    Supported modes:
    - 'merge_update': Updates matching companies and appends new ones without wiping DB.
    - 'append_only': Only inserts companies not currently in DB.
    Preserves DB as primary truth; records source as 'csv_import'.
    """
    init_company_database(db_path)
    conn = get_db_connection(db_path)
    now_iso = datetime.now(timezone.utc).isoformat()

    inserted_count = 0
    updated_count = 0
    triggers_added = 0

    with conn:
        for _, row in df.iterrows():
            c_name = str(row.get("company", "") or "").strip()
            if not c_name:
                continue

            c_domain = str(row.get("domain", "") or "").strip()
            c_seg = str(row.get("segment", "General Industrial") or "General Industrial").strip()
            c_tier = int(row.get("source_tier", 3) if pd.notna(row.get("source_tier")) else 3)
            cid = generate_company_id(c_name, c_domain)

            existing = conn.execute(
                "SELECT company_id FROM companies WHERE company_id = ? OR normalized_name = ?",
                (cid, normalize_str(c_name)),
            ).fetchone()

            if existing:
                if override_mode == "merge_update":
                    conn.execute(
                        """
                        UPDATE companies
                        SET segment = ?, domain = ?, normalized_domain = ?, source_tier = ?, updated_at = ?
                        WHERE company_id = ?;
                        """,
                        (c_seg, c_domain, normalize_str(c_domain), c_tier, now_iso, existing["company_id"]),
                    )
                    updated_count += 1
                target_cid = existing["company_id"]
            else:
                conn.execute(
                    """
                    INSERT INTO companies (
                        company_id, company_name, normalized_name, domain, normalized_domain,
                        segment, source_tier, created_source, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, 'csv_import', ?, ?);
                    """,
                    (
                        cid,
                        c_name,
                        normalize_str(c_name),
                        c_domain,
                        normalize_str(c_domain),
                        c_seg,
                        c_tier,
                        now_iso,
                        now_iso,
                    ),
                )
                conn.execute(
                    """
                    INSERT OR IGNORE INTO company_enrichment_status (
                        company_id, enrichment_status, priority_tier, fields_enriched_count,
                        fields_unknown_count, sec_edgar_status, wikidata_status
                    ) VALUES (?, 'not_started', 2, 0, 0, 'not_started', 'not_started');
                    """,
                    (cid,),
                )
                inserted_count += 1
                target_cid = cid

            # Record trigger if provided
            t_type = str(row.get("trigger_type", "") or "").strip()
            t_sum = str(row.get("trigger_summary", "") or "").strip()
            if t_type or t_sum:
                conn.execute(
                    """
                    INSERT INTO company_triggers (
                        company_id, trigger_type, trigger_date, trigger_summary,
                        trigger_source_url, scanned_at, source
                    ) VALUES (?, ?, ?, ?, ?, ?, 'csv_import');
                    """,
                    (
                        target_cid,
                        t_type,
                        str(row.get("trigger_date", "") or "").strip(),
                        t_sum,
                        str(row.get("trigger_source_url", "") or "").strip(),
                        str(row.get("scanned_at", "") or "").strip() or now_iso[:10],
                    ),
                )
                triggers_added += 1

    return {
        "inserted_count": inserted_count,
        "updated_count": updated_count,
        "triggers_added": triggers_added,
        "mode": override_mode,
    }


def get_all_companies_dataframe(db_path: Optional[Union[str, Path]] = None) -> pd.DataFrame:
    """
    Returns a pandas DataFrame of all companies joined with their enrichment status.
    Used for reading data into Streamlit UI and ranker.
    """
    init_company_database(db_path)
    conn = get_db_connection(db_path)

    query = """
        SELECT 
            c.company_id,
            c.company_name,
            c.normalized_name,
            c.domain,
            c.normalized_domain,
            c.segment,
            c.source_tier,
            c.created_source,
            c.created_at,
            c.updated_at,
            COALESCE(s.enrichment_status, 'not_started') as enrichment_status,
            COALESCE(s.priority_tier, 2) as priority_tier,
            s.last_enriched_at,
            s.stale_after,
            COALESCE(s.fields_enriched_count, 0) as fields_enriched_count,
            COALESCE(s.fields_unknown_count, 0) as fields_unknown_count,
            s.sec_edgar_status,
            s.wikidata_status,
            s.error_message
        FROM companies c
        LEFT JOIN company_enrichment_status s ON c.company_id = s.company_id
        ORDER BY c.company_name ASC;
    """
    df = pd.read_sql_query(query, conn)
    return df


def get_company_field_provenance(
    company_id: str,
    db_path: Optional[Union[str, Path]] = None,
) -> Dict[str, Dict[str, Any]]:
    """
    Retrieves all field provenance records for a company.
    Returns dictionary keyed by field_name:
    {
        "revenue": {
            "value": "$25.5B",
            "value_status": "exact",
            "source_url": "https://data.sec.gov/...",
            "source_type": "sec_edgar",
            "source_date": "2026-02-15",
            "confidence": "HIGH",
            "retrieved_at": "...",
            "is_stale": 0
        }, ...
    }
    """
    init_company_database(db_path)
    conn = get_db_connection(db_path)

    cursor = conn.execute(
        """
        SELECT field_name, field_value, value_status, source_url, source_type,
               source_date, confidence, retrieved_at, is_stale, raw_evidence_snippet
        FROM company_field_provenance
        WHERE company_id = ?
        ORDER BY field_name ASC;
        """,
        (company_id,),
    )

    records = {}
    for row in cursor.fetchall():
        records[row["field_name"]] = {
            "value": row["field_value"],
            "field_value": row["field_value"],
            "value_status": row["value_status"],
            "source_url": row["source_url"],
            "source_type": row["source_type"],
            "source_date": row["source_date"],
            "confidence": row["confidence"],
            "retrieved_at": row["retrieved_at"],
            "is_stale": bool(row["is_stale"]),
            "raw_evidence_snippet": row["raw_evidence_snippet"],
        }
    return records


def upsert_field_provenance_records(
    company_id: str,
    provenance_list: List[Dict[str, Any]],
    db_path: Optional[Union[str, Path]] = None,
) -> None:
    """
    Stores or updates field-level provenance records adhering strictly to provenance rules.
    """
    init_company_database(db_path)
    conn = get_db_connection(db_path)
    now_iso = datetime.now(timezone.utc).isoformat()

    with conn:
        for p in provenance_list:
            field_name = str(p.get("field_name", "")).strip()
            if not field_name:
                continue

            val = p.get("field_value")
            val_str = str(val) if val is not None else None
            val_status = str(p.get("value_status", "unknown")).lower()
            if val_status not in VALUE_STATUSES:
                val_status = "unknown"

            src_type = str(p.get("source_type", "none")).lower()
            if src_type not in SOURCE_TYPES:
                src_type = "none"

            conf = str(p.get("confidence", "UNVERIFIED")).upper()
            if conf not in CONFIDENCE_TIERS:
                conf = "UNVERIFIED"

            conn.execute(
                """
                INSERT INTO company_field_provenance (
                    company_id, field_name, field_value, value_status,
                    source_url, source_type, source_date, confidence,
                    retrieved_at, is_stale, raw_evidence_snippet
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?)
                ON CONFLICT(company_id, field_name) DO UPDATE SET
                    field_value = excluded.field_value,
                    value_status = excluded.value_status,
                    source_url = excluded.source_url,
                    source_type = excluded.source_type,
                    source_date = excluded.source_date,
                    confidence = excluded.confidence,
                    retrieved_at = excluded.retrieved_at,
                    is_stale = 0,
                    raw_evidence_snippet = excluded.raw_evidence_snippet;
                """,
                (
                    company_id,
                    field_name,
                    val_str,
                    val_status,
                    p.get("source_url"),
                    src_type,
                    p.get("source_date"),
                    conf,
                    p.get("retrieved_at", now_iso),
                    p.get("raw_evidence_snippet"),
                ),
            )


def update_enrichment_status(
    company_id: str,
    status: str,
    sec_status: Optional[str] = None,
    wikidata_status: Optional[str] = None,
    error_message: Optional[str] = None,
    db_path: Optional[Union[str, Path]] = None,
) -> None:
    """
    Updates the enrichment status lifecycle record.
    Calculates enriched vs unknown field counts directly from the provenance table.
    """
    init_company_database(db_path)
    conn = get_db_connection(db_path)
    now_dt = datetime.now(timezone.utc)
    now_iso = now_dt.isoformat()
    stale_iso = (now_dt + timedelta(days=DEFAULT_STALE_DAYS)).isoformat()

    if status not in ENRICHMENT_STATUSES:
        raise ValueError(f"Invalid status '{status}'. Must be one of {ENRICHMENT_STATUSES}")

    with conn:
        # Count enriched vs unknown fields
        counts = conn.execute(
            """
            SELECT 
                SUM(CASE WHEN value_status != 'unknown' AND field_value IS NOT NULL THEN 1 ELSE 0 END) as enriched,
                SUM(CASE WHEN value_status = 'unknown' OR field_value IS NULL THEN 1 ELSE 0 END) as unknowns
            FROM company_field_provenance
            WHERE company_id = ?;
            """,
            (company_id,),
        ).fetchone()

        enriched_cnt = counts["enriched"] or 0
        unknowns_cnt = counts["unknowns"] or 0

        conn.execute(
            """
            INSERT INTO company_enrichment_status (
                company_id, enrichment_status, priority_tier, last_attempted_at,
                last_enriched_at, stale_after, fields_enriched_count,
                fields_unknown_count, error_message, sec_edgar_status, wikidata_status
            ) VALUES (?, ?, 2, ?, ?, ?, ?, ?, ?, COALESCE(?, 'not_started'), COALESCE(?, 'not_started'))
            ON CONFLICT(company_id) DO UPDATE SET
                enrichment_status = excluded.enrichment_status,
                last_attempted_at = excluded.last_attempted_at,
                last_enriched_at = CASE WHEN excluded.enrichment_status IN ('complete', 'partial') THEN excluded.last_enriched_at ELSE company_enrichment_status.last_enriched_at END,
                stale_after = CASE WHEN excluded.enrichment_status IN ('complete', 'partial') THEN excluded.stale_after ELSE company_enrichment_status.stale_after END,
                fields_enriched_count = excluded.fields_enriched_count,
                fields_unknown_count = excluded.fields_unknown_count,
                error_message = excluded.error_message,
                sec_edgar_status = COALESCE(excluded.sec_edgar_status, company_enrichment_status.sec_edgar_status),
                wikidata_status = COALESCE(excluded.wikidata_status, company_enrichment_status.wikidata_status);
            """,
            (
                company_id,
                status,
                now_iso,
                now_iso if status in ("complete", "partial") else None,
                stale_iso if status in ("complete", "partial") else None,
                enriched_cnt,
                unknowns_cnt,
                error_message,
                sec_status,
                wikidata_status,
            ),
        )


def check_and_mark_stale_records(db_path: Optional[Union[str, Path]] = None) -> int:
    """
    Evaluates records against stale_after threshold (>90 days) and marks status 'stale'.
    Returns number of records marked stale.
    """
    init_company_database(db_path)
    conn = get_db_connection(db_path)
    now_iso = datetime.now(timezone.utc).isoformat()

    with conn:
        cursor = conn.execute(
            """
            UPDATE company_enrichment_status
            SET enrichment_status = 'stale'
            WHERE enrichment_status IN ('complete', 'partial')
              AND stale_after IS NOT NULL
              AND stale_after < ?;
            """,
            (now_iso,),
        )
        updated = cursor.rowcount

        # Mark corresponding provenance records as is_stale = 1
        conn.execute(
            """
            UPDATE company_field_provenance
            SET is_stale = 1
            WHERE company_id IN (
                SELECT company_id FROM company_enrichment_status WHERE enrichment_status = 'stale'
            );
            """
        )
        return updated


def get_enrichment_summary_stats(db_path: Optional[Union[str, Path]] = None) -> Dict[str, Any]:
    """
    Returns aggregate enrichment and provenance statistics across the master database.
    Used for executive dashboards, overview KPI reporting, and backfill monitoring.
    """
    init_company_database(db_path)
    conn = get_db_connection(db_path)

    total_companies = conn.execute("SELECT COUNT(*) as cnt FROM companies;").fetchone()["cnt"]

    # Status distribution
    status_rows = conn.execute(
        """
        SELECT COALESCE(s.enrichment_status, 'not_started') as status, COUNT(*) as cnt
        FROM companies c
        LEFT JOIN company_enrichment_status s ON c.company_id = s.company_id
        GROUP BY status;
        """
    ).fetchall()

    status_counts = {st: 0 for st in ENRICHMENT_STATUSES}
    for r in status_rows:
        status_counts[r["status"]] = r["cnt"]

    enriched_total = status_counts["complete"] + status_counts["partial"]
    coverage_pct = round((enriched_total / total_companies * 100.0), 1) if total_companies > 0 else 0.0

    # Connector coverage
    conn_stats = conn.execute(
        """
        SELECT 
            SUM(CASE WHEN sec_edgar_status = 'complete' THEN 1 ELSE 0 END) as sec_complete,
            SUM(CASE WHEN sec_edgar_status = 'partial' THEN 1 ELSE 0 END) as sec_partial,
            SUM(CASE WHEN wikidata_status = 'complete' THEN 1 ELSE 0 END) as wiki_complete,
            SUM(CASE WHEN wikidata_status = 'partial' THEN 1 ELSE 0 END) as wiki_partial
        FROM company_enrichment_status;
        """
    ).fetchone()

    # Provenance value status counts
    prov_status_rows = conn.execute(
        """
        SELECT value_status, COUNT(*) as cnt
        FROM company_field_provenance
        GROUP BY value_status;
        """
    ).fetchall()
    value_status_counts = {vs: 0 for vs in VALUE_STATUSES}
    for r in prov_status_rows:
        value_status_counts[r["value_status"]] = r["cnt"]

    # Provenance source type counts
    prov_src_rows = conn.execute(
        """
        SELECT source_type, COUNT(*) as cnt
        FROM company_field_provenance
        GROUP BY source_type;
        """
    ).fetchall()
    source_type_counts = {}
    for r in prov_src_rows:
        source_type_counts[r["source_type"]] = r["cnt"]

    total_prov_fields = conn.execute("SELECT COUNT(*) as cnt FROM company_field_provenance;").fetchone()["cnt"]

    return {
        "total_companies": total_companies,
        "status_counts": status_counts,
        "enriched_count": enriched_total,
        "coverage_pct": coverage_pct,
        "sec_edgar_complete": conn_stats["sec_complete"] or 0,
        "sec_edgar_partial": conn_stats["sec_partial"] or 0,
        "wikidata_complete": conn_stats["wiki_complete"] or 0,
        "wikidata_partial": conn_stats["wiki_partial"] or 0,
        "total_provenance_fields": total_prov_fields,
        "value_status_counts": value_status_counts,
        "source_type_counts": source_type_counts,
    }

