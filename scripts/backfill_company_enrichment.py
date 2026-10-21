#!/usr/bin/env python3
"""
Headless Company Enrichment Backfill Script (Phase 4 Foundation)
EON Commercial Intelligence | External Review Build

Decoupled CLI worker for background batch enrichment:
- Fully separated from Streamlit session lifecycle to prevent UI worker blocking
- Rate-paced querying across SEC EDGAR Submissions API and Wikidata MediaWiki API
- Bounded batch execution with priority tier ordering (tier 1 accounts first)
- Concurrency-safe SQLite WAL transaction handling
- Comprehensive command-line reporting and status auditing

Usage:
    python3 scripts/backfill_company_enrichment.py --batch-size 25 --max-total 50
    python3 scripts/backfill_company_enrichment.py --status-report
"""

import argparse
import logging
import os
from pathlib import Path
import sys
import time
from typing import Optional

from datetime import datetime
import json
import sqlite3
from typing import Any, Dict, List, Optional

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from dashboard.company_db import (
    DEFAULT_DB_PATH,
    init_company_database,
    get_db_connection,
    get_enrichment_summary_stats,
    check_and_mark_stale_records,
)
from dashboard.enrichment_engine import CompanyEnrichmentEngine

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("backfill")


def make_timestamped_backup(db_path: Path) -> Path:
    """Creates a consistent, atomic SQLite snapshot before live batch writes."""
    backup_dir = db_path.parent / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = backup_dir / f"{db_path.stem}_backup_{timestamp}.db"

    src = sqlite3.connect(db_path)
    dst = sqlite3.connect(backup_path)
    with dst:
        src.backup(dst)
    dst.close()
    src.close()
    return backup_path


def print_status_report(db_path: Path) -> None:
    """Prints a concise tabular status report of master database enrichment."""
    stats = get_enrichment_summary_stats(db_path)
    total = stats["total_companies"]
    st_counts = stats["status_counts"]
    enriched = stats["enriched_count"]
    cov = stats["coverage_pct"]

    print("=" * 65)
    print(" 🏛️  EON Master Company Database — Enrichment Status Report")
    print("=" * 65)
    print(f" Database Path:         {db_path}")
    print(f" Total Master Accounts: {total:,}")
    print(f" Total Enriched:        {enriched:,} ({cov}% coverage)")
    print("-" * 65)
    print(f" • Complete (4+ fields):   {st_counts.get('complete', 0):>6,}")
    print(f" • Partial (1-3 fields):    {st_counts.get('partial', 0):>6,}")
    print(f" • Not Started (Pending):   {st_counts.get('not_started', 0):>6,}")
    print(f" • Stale (>90 days):        {st_counts.get('stale', 0):>6,}")
    print(f" • Failed (Connector err):  {st_counts.get('failed', 0):>6,}")
    print("-" * 65)
    print(f" SEC EDGAR Filings (Statutory): {stats['sec_edgar_complete'] + stats['sec_edgar_partial']:,}")
    print(f" Wikidata Claims (Secondary):   {stats['wikidata_complete'] + stats['wikidata_partial']:,}")
    print(f" Total Provenance Field Records: {stats['total_provenance_fields']:,}")
    print("=" * 65)


def run_backfill(
    db_path: Path,
    batch_size: int = 25,
    max_total: int = 100,
    priority_first: bool = True,
    dry_run: bool = False,
    run_id: Optional[str] = None,
    backup_before_run: bool = True,
) -> int:
    """
    Executes a bounded batch enrichment backfill with full audit trail.
    Returns the number of companies processed.
    """
    init_company_database(db_path)
    run_id = run_id or f"run_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

    # Check and update stale records before backfill
    stale_count = check_and_mark_stale_records(db_path)
    if stale_count > 0:
        logger.info(f"Marked {stale_count} records as stale (>90 days old).")

    conn = get_db_connection(db_path)

    # Candidate query
    if priority_first:
        query = """
            SELECT c.company_id, c.company_name, c.domain, s.priority_tier, s.enrichment_status
            FROM companies c
            JOIN company_enrichment_status s ON c.company_id = s.company_id
            WHERE s.enrichment_status IN ('not_started', 'stale')
            ORDER BY 
                s.priority_tier ASC,
                (SELECT COUNT(*) FROM company_triggers WHERE company_id = c.company_id) DESC,
                c.source_tier ASC,
                c.company_name ASC
            LIMIT ?;
        """
    else:
        query = """
            SELECT c.company_id, c.company_name, c.domain, s.priority_tier, s.enrichment_status
            FROM companies c
            JOIN company_enrichment_status s ON c.company_id = s.company_id
            WHERE s.enrichment_status IN ('not_started', 'stale')
            ORDER BY c.id ASC
            LIMIT ?;
        """

    fetch_limit = min(batch_size, max_total)
    rows = conn.execute(query, (fetch_limit,)).fetchall()

    if not rows:
        logger.info("✅ All companies in master database are already enriched. Zero pending records.")
        return 0

    total_to_process = len(rows)
    logger.info(f"Starting headless backfill: {total_to_process} companies queued (batch size: {batch_size}, max: {max_total}, run_id: {run_id}).")

    if dry_run:
        logger.info("[DRY RUN] Would process the following accounts:")
        for idx, r in enumerate(rows, 1):
            logger.info(f"  {idx}. {r['company_name']} ({r['domain'] or 'no domain'}) [tier {r['priority_tier']}]")
        return total_to_process

    # 1. Condition 1: Make SQLite backup before live writes
    backup_file: Optional[Path] = None
    if backup_before_run:
        backup_file = make_timestamped_backup(db_path)
        logger.info(f"🔒 SQLite backup created: {backup_file}")
        logger.info(f"🔄 Rollback command if needed: cp {backup_file} {db_path}")

    engine = CompanyEnrichmentEngine(db_path=db_path)
    processed = 0
    start_time = time.time()

    per_company_audit: List[Dict[str, Any]] = []
    sec_stats = {"success": 0, "not_found": 0, "error": 0}
    wiki_stats = {"accepted": 0, "unknown": 0, "rejected_conflict": 0}
    field_counts = {"current_total": 0, "historical_total": 0, "unknown_total": 0}
    ambiguous_candidates_log: List[Dict[str, Any]] = []

    for idx, r in enumerate(rows, 1):
        cid = r["company_id"]
        cname = r["company_name"]
        cdomain = r["domain"]
        comp_start = time.time()
        logger.info(f"[{idx}/{total_to_process}] Enriching '{cname}' (ID: {cid})...")

        audit_entry: Dict[str, Any] = {
            "company_id": cid,
            "company_name": cname,
            "domain": cdomain,
            "priority_tier": r["priority_tier"],
        }

        try:
            res = engine.enrich_company_by_id(cid, force=True)
            comp_elapsed = time.time() - comp_start
            status = res.get("enrichment_status", "unknown")
            fields_cnt = res.get("fields_enriched_count", 0)

            sec_res = res.get("sec_result", {})
            wiki_res = res.get("wiki_result", {})
            merged = res.get("merged_fields", {})

            # 1. SEC status classification
            raw_sec_st = sec_res.get("source_status", "error")
            if raw_sec_st == "success":
                sec_classification = "success"
                sec_stats["success"] += 1
            elif raw_sec_st == "not_found":
                sec_classification = "no-match"
                sec_stats["not_found"] += 1
            else:
                sec_classification = "error"
                sec_stats["error"] += 1

            # 2. Wikidata status classification
            raw_wiki_st = wiki_res.get("source_status", "error")
            wiki_evals = wiki_res.get("evaluated_candidates", [])
            has_conflict = any(e.get("decision") == "rejected_conflict" for e in wiki_evals)

            if raw_wiki_st == "success":
                wiki_classification = "accepted"
                wiki_stats["accepted"] += 1
            elif has_conflict:
                wiki_classification = "rejected-conflict"
                wiki_stats["rejected_conflict"] += 1
            else:
                wiki_classification = "unknown"
                wiki_stats["unknown"] += 1

            # Track ambiguous candidates
            if len(wiki_evals) > 1 or any(e.get("decision") in ("rejected_conflict", "rejected_insufficient_corroboration") for e in wiki_evals):
                ambiguous_candidates_log.append({
                    "company_name": cname,
                    "domain": cdomain,
                    "resolved_qid": wiki_res.get("qid"),
                    "candidates": wiki_evals,
                })

            # 3. Field breakdown: current vs historical vs unknown
            curr_fields = [k for k, v in merged.items() if v.get("value_status") != "unknown" and v.get("field_value") is not None and k not in ("historical_annual_revenue", "historical_employee_count")]
            hist_fields = [k for k, v in merged.items() if k in ("historical_annual_revenue", "historical_employee_count") and v.get("field_value") is not None]
            unkn_fields = [k for k, v in merged.items() if v.get("value_status") == "unknown" or v.get("field_value") is None]

            field_counts["current_total"] += len(curr_fields)
            field_counts["historical_total"] += len(hist_fields)
            field_counts["unknown_total"] += len(unkn_fields)

            audit_entry.update({
                "enrichment_status": status,
                "elapsed_seconds": round(comp_elapsed, 2),
                "sec_classification": sec_classification,
                "sec_cik": sec_res.get("cik"),
                "sec_fields": [f["field_name"] for f in sec_res.get("fields", []) if f.get("value_status") != "unknown"],
                "wikidata_classification": wiki_classification,
                "wikidata_qid": wiki_res.get("qid"),
                "wikidata_corroboration_reason": wiki_res.get("corroboration_reason"),
                "evaluated_candidates": wiki_evals,
                "field_counts": {
                    "current_count": len(curr_fields),
                    "historical_count": len(hist_fields),
                    "unknown_count": len(unkn_fields),
                },
                "current_fields": curr_fields,
                "historical_fields": hist_fields,
                "unknown_fields": unkn_fields,
                "error": None,
            })

            logger.info(
                f"  -> Result: {status.upper()} | SEC: {sec_classification} | Wiki: {wiki_classification} "
                f"| Fields: {len(curr_fields)} curr, {len(hist_fields)} hist, {len(unkn_fields)} unkn ({comp_elapsed:.2f}s)"
            )
            processed += 1
        except Exception as e:
            comp_elapsed = time.time() - comp_start
            logger.error(f"  -> Failed to enrich '{cname}': {e}")
            audit_entry.update({
                "enrichment_status": "error",
                "elapsed_seconds": round(comp_elapsed, 2),
                "error": str(e),
            })

        per_company_audit.append(audit_entry)

        # Condition 4: Continue on individual errors, do not retry failure in same invocation
        time.sleep(0.15)

    total_elapsed = time.time() - start_time
    sec_api_calls = getattr(engine.sec_connector, "request_count", 0)
    wiki_api_calls = getattr(engine.wikidata_connector, "request_count", 0)
    total_api_calls = sec_api_calls + wiki_api_calls

    audit_summary = {
        "run_id": run_id,
        "timestamp": datetime.now().isoformat(),
        "database_path": str(db_path),
        "backup_path": str(backup_file) if backup_file else None,
        "rollback_command": f"cp {backup_file} {db_path}" if backup_file else None,
        "accounts_queued": total_to_process,
        "accounts_processed": processed,
        "elapsed_seconds_total": round(total_elapsed, 2),
        "avg_seconds_per_account": round(total_elapsed / max(1, processed), 2),
        "api_calls": {
            "sec_edgar_requests": sec_api_calls,
            "wikidata_requests": wiki_api_calls,
            "total_requests": total_api_calls,
        },
        "sec_summary": sec_stats,
        "wikidata_summary": wiki_stats,
        "field_counts_summary": field_counts,
        "ambiguous_candidates_count": len(ambiguous_candidates_log),
        "companies": per_company_audit,
    }

    # Save JSON audit report
    audit_file = db_path.parent / f"enrichment_pilot_audit_{run_id}.json"
    try:
        with open(audit_file, "w", encoding="utf-8") as f:
            json.dump(audit_summary, f, indent=2)
        logger.info(f"📊 Full audit log written to: {audit_file}")
    except Exception as e:
        logger.warning(f"Could not save audit log file: {e}")

    logger.info(
        f"Batch completed: {processed}/{total_to_process} companies processed in {total_elapsed:.1f}s "
        f"({total_elapsed/max(1, processed):.2f}s/comp). Total API calls: {total_api_calls} (SEC: {sec_api_calls}, Wiki: {wiki_api_calls})."
    )
    return processed


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Headless backfill worker for company statutory and firmographic enrichment."
    )
    parser.add_argument(
        "--db-path",
        type=Path,
        default=DEFAULT_DB_PATH,
        help="Path to SQLite master database.",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=25,
        help="Number of accounts to process per batch run (default: 25).",
    )
    parser.add_argument(
        "--max-total",
        type=int,
        default=100,
        help="Maximum total accounts to process in this invocation (default: 100).",
    )
    parser.add_argument(
        "--priority-first",
        action="store_true",
        default=True,
        help="Process priority tier 1 accounts before tier 2 (default: True).",
    )
    parser.add_argument(
        "--status-report",
        action="store_true",
        help="Print enrichment status report and exit without executing backfill.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Simulate backfill without querying live APIs or updating database.",
    )
    parser.add_argument(
        "--run-id",
        type=str,
        default=None,
        help="Identifier for this enrichment run/audit batch.",
    )
    parser.add_argument(
        "--no-backup",
        action="store_true",
        help="Skip automatic SQLite pre-run backup.",
    )

    args = parser.parse_args()

    if args.status_report:
        print_status_report(args.db_path)
        sys.exit(0)

    try:
        run_backfill(
            db_path=args.db_path,
            batch_size=args.batch_size,
            max_total=args.max_total,
            priority_first=args.priority_first,
            dry_run=args.dry_run,
            run_id=args.run_id,
            backup_before_run=not args.no_backup,
        )
        print_status_report(args.db_path)
    except KeyboardInterrupt:
        logger.warning("\nBackfill interrupted by user. Partial progress has been saved.")
        sys.exit(130)


if __name__ == "__main__":
    main()
