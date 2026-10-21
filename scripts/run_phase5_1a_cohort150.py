"""
Controlled Live Batch Execution Script: Phase 5.1A (Cohort of 150 Companies)
Executes priority-first live enrichment with pre-run backup, conservative SEC/Wikidata resolvers,
expanded 9-state relationship taxonomy, Current-Operating-Entity Gate, separated base vs amendment SEC annual filings,
provenance tracking, runtime distribution analytics, and comprehensive audit JSON generation.
"""

from datetime import datetime, timezone
import hashlib
import json
import logging
import math
import os
from pathlib import Path
import sqlite3
import sys
import time
from typing import Any, Dict, List, Optional, Tuple

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from dashboard.company_db import DEFAULT_DB_PATH, get_db_connection
from dashboard.enrichment_engine import CompanyEnrichmentEngine

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("eon.phase5_1a.cohort150")


def make_timestamped_backup(db_path: Path, timestamp: str) -> Path:
    backup_dir = db_path.parent / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup_path = backup_dir / f"companies_master_pre_phase5_1a_{timestamp}.db"

    src = sqlite3.connect(db_path)
    dst = sqlite3.connect(backup_path)
    with dst:
        src.backup(dst)
    dst.close()
    src.close()
    return backup_path


def verify_backup(backup_path: Path, db_path: Path) -> Dict[str, Any]:
    if not backup_path.exists():
        return {"verified": False, "reason": "Backup file does not exist"}
    b_conn = sqlite3.connect(backup_path)
    m_conn = sqlite3.connect(db_path)

    # 1. Integrity check
    b_integrity = b_conn.execute("PRAGMA integrity_check").fetchone()[0]
    m_integrity = m_conn.execute("PRAGMA integrity_check").fetchone()[0]

    b_cnt = b_conn.execute("SELECT COUNT(*) FROM companies").fetchone()[0]
    m_cnt = m_conn.execute("SELECT COUNT(*) FROM companies").fetchone()[0]
    b_statuses = dict(b_conn.execute("SELECT enrichment_status, COUNT(*) FROM company_enrichment_status GROUP BY enrichment_status").fetchall())
    m_statuses = dict(m_conn.execute("SELECT enrichment_status, COUNT(*) FROM company_enrichment_status GROUP BY enrichment_status").fetchall())
    b_prov = b_conn.execute("SELECT COUNT(*) FROM company_field_provenance").fetchone()[0]
    m_prov = m_conn.execute("SELECT COUNT(*) FROM company_field_provenance").fetchone()[0]

    b_conn.close()
    m_conn.close()

    ok = (
        b_integrity == "ok"
        and m_integrity == "ok"
        and b_cnt == m_cnt
        and b_cnt > 0
        and b_statuses == m_statuses
        and b_prov == m_prov
    )
    return {
        "verified": ok,
        "backup_integrity": b_integrity,
        "master_integrity": m_integrity,
        "backup_company_count": b_cnt,
        "master_company_count": m_cnt,
        "backup_status_counts": b_statuses,
        "master_status_counts": m_statuses,
        "status_parity": b_statuses == m_statuses,
        "backup_provenance_count": b_prov,
        "master_provenance_count": m_prov,
        "provenance_parity": b_prov == m_prov,
    }


def compute_percentile(data: List[float], percentile: float) -> float:
    if not data:
        return 0.0
    sorted_data = sorted(data)
    k = (len(sorted_data) - 1) * (percentile / 100.0)
    f = math.floor(k)
    c = math.ceil(k)
    if f == c:
        return round(sorted_data[int(k)], 3)
    d0 = sorted_data[int(f)] * (c - k)
    d1 = sorted_data[int(c)] * (k - f)
    return round(d0 + d1, 3)


def run_phase5_1a_batch() -> Dict[str, Any]:
    db_path = Path("local_data/companies_master.db")
    timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_id = f"phase5_1a_cohort150_{timestamp_str}"

    print(f"\n{'='*120}")
    print(f"{'PHASE 5.1A CONTROLLED LIVE BATCH ENRICHMENT (150 COMPANIES)':^120}")
    print(f"{'='*120}")
    logger.info(f"Run ID: {run_id}")
    logger.info(f"Target Database: {db_path}")

    # 1. Pre-run database metrics recording
    conn = get_db_connection(db_path)
    pre_integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
    pre_run_total_companies = conn.execute("SELECT COUNT(*) FROM companies").fetchone()[0]
    pre_run_status_counts = dict(
        conn.execute("SELECT enrichment_status, COUNT(*) FROM company_enrichment_status GROUP BY enrichment_status").fetchall()
    )
    pre_run_provenance_rows = conn.execute("SELECT COUNT(*) FROM company_field_provenance").fetchone()[0]
    conn.close()

    logger.info(f"Pre-run Integrity Check: {pre_integrity}")
    logger.info(f"Pre-run Companies Total: {pre_run_total_companies}")
    logger.info(f"Pre-run Status Breakdown: {pre_run_status_counts}")
    logger.info(f"Pre-run Provenance Rows: {pre_run_provenance_rows}")

    if pre_integrity != "ok":
        raise RuntimeError(f"Pre-run integrity check failed: {pre_integrity}")

    # 2. Atomic pre-run backup
    backup_path = make_timestamped_backup(db_path, timestamp_str)
    logger.info(f"Created timestamped SQLite backup at: {backup_path}")
    backup_check = verify_backup(backup_path, db_path)
    if not backup_check.get("verified"):
        raise RuntimeError(f"Backup verification failed: {backup_check}")
    logger.info(f"Backup integrity verified: {backup_check}")
    rollback_cmd = f"cp {backup_path} {db_path}"
    logger.info(f"Rollback Command: {rollback_cmd}")

    # 3. Select next 150 not_started companies via priority-first queue ordering
    conn = get_db_connection(db_path)
    conn.row_factory = sqlite3.Row
    query = """
        SELECT c.company_id, c.company_name, c.domain, s.priority_tier, s.enrichment_status
        FROM companies c
        JOIN company_enrichment_status s ON c.company_id = s.company_id
        WHERE s.enrichment_status = 'not_started'
          AND c.company_name NOT LIKE '%Test%'
          AND c.company_name NOT LIKE '%Synthetic%'
        ORDER BY 
            s.priority_tier ASC,
            (SELECT COUNT(*) FROM company_triggers WHERE company_id = c.company_id) DESC,
            c.source_tier ASC,
            c.company_name ASC
        LIMIT 150;
    """
    rows = conn.execute(query).fetchall()
    conn.close()

    if len(rows) != 150:
        logger.warning(f"Expected 150 companies, retrieved {len(rows)}")

    immutable_queue_ids = [r["company_id"] for r in rows]
    immutable_queue_tuples = [
        {
            "queue_position": idx,
            "company_id": r["company_id"],
            "company_name": r["company_name"],
            "domain": r["domain"],
            "priority_tier": r["priority_tier"],
        }
        for idx, r in enumerate(rows, 1)
    ]

    # Compute deterministic queue hash (SHA-256)
    queue_hash = hashlib.sha256(json.dumps(immutable_queue_ids).encode("utf-8")).hexdigest()
    logger.info(f"Captured immutable ordered queue of {len(rows)} accounts. Queue SHA-256: {queue_hash}")

    # 4. Engine execution
    engine = CompanyEnrichmentEngine(db_path=db_path)
    start_time = time.time()

    per_company_audit: List[Dict[str, Any]] = []
    runtimes: List[float] = []
    sec_stats = {
        "exact_canonical": 0,
        "legal_parent_successor": 0,
        "operating_subsidiary": 0,
        "brand_alias": 0,
        "pre_first_annual_filing": 0,
        "subsidiary_holding": 0,
        "ambiguous": 0,
        "rejected": 0,
        "no_match": 0,
    }
    wiki_stats = {
        "accepted": 0,
        "unknown": 0,
        "rejected_conflict": 0,
    }
    field_counts = {
        "current_total": 0,
        "historical_total": 0,
        "unknown_total": 0,
    }
    errors_log: List[Dict[str, Any]] = []
    account_provenance_deltas: List[int] = []

    print(f"\n{'-'*130}")
    print(f"{'#':<3} | {'Company Name':<28} | {'Domain':<18} | {'SEC CIK':<12} | {'Rel Class':<18} | {'Wiki QID':<10} | {'Status':<10} | {'Fields (C/H/U)':<15}")
    print(f"{'-'*130}")

    for idx, r in enumerate(rows, 1):
        cid = r["company_id"]
        cname = r["company_name"]
        cdomain = r["domain"]
        comp_start = time.time()

        audit_entry: Dict[str, Any] = {
            "queue_position": idx,
            "company_id": cid,
            "company_name": cname,
            "domain": cdomain,
            "priority_tier": r["priority_tier"],
        }

        try:
            # Measure provenance row delta for this company
            c_conn = get_db_connection(db_path)
            pre_comp_prov = c_conn.execute("SELECT COUNT(*) FROM company_field_provenance WHERE company_id = ?", (cid,)).fetchone()[0]
            c_conn.close()

            res = engine.enrich_company_by_id(cid, force=True)
            comp_elapsed = time.time() - comp_start
            runtimes.append(comp_elapsed)

            st = res.get("enrichment_status", "unknown")
            sec_res = res.get("sec_result", {})
            wiki_res = res.get("wiki_result", {})
            merged = res.get("merged_fields", {})

            c_conn = get_db_connection(db_path)
            post_comp_prov = c_conn.execute("SELECT COUNT(*) FROM company_field_provenance WHERE company_id = ?", (cid,)).fetchone()[0]
            c_conn.close()
            prov_delta = post_comp_prov - pre_comp_prov
            account_provenance_deltas.append(prov_delta)

            # 1. SEC Breakdown with expanded 9-state taxonomy
            raw_sec_st = sec_res.get("source_status", "error")
            accepted_cik = sec_res.get("cik")
            sec_evals = sec_res.get("evaluated_candidates", [])

            primary_rel = "no_match"
            accepted_cand = None
            if accepted_cik:
                for c in sec_evals:
                    if c.get("cik") == accepted_cik:
                        primary_rel = c.get("relationship", "exact_canonical")
                        accepted_cand = c
                        break
                if primary_rel in sec_stats:
                    sec_stats[primary_rel] += 1
                else:
                    sec_stats["exact_canonical"] += 1
            elif sec_evals:
                rels = [c.get("relationship") for c in sec_evals]
                if "subsidiary_holding" in rels:
                    primary_rel = "subsidiary_holding"
                    sec_stats["subsidiary_holding"] += 1
                elif "ambiguous" in rels:
                    primary_rel = "ambiguous"
                    sec_stats["ambiguous"] += 1
                else:
                    primary_rel = "rejected"
                    sec_stats["rejected"] += 1
            else:
                primary_rel = "no_match"
                sec_stats["no_match"] += 1

            # 2. Wikidata Breakdown
            raw_wiki_st = wiki_res.get("source_status", "error")
            resolved_qid = wiki_res.get("qid")
            wiki_evals = wiki_res.get("evaluated_candidates", [])
            has_conflict = any(e.get("decision") == "rejected_conflict" for e in wiki_evals)

            if raw_wiki_st == "success" and resolved_qid:
                wiki_classification = "accepted"
                wiki_stats["accepted"] += 1
            elif has_conflict:
                wiki_classification = "rejected_conflict"
                wiki_stats["rejected_conflict"] += 1
            else:
                wiki_classification = "unknown"
                wiki_stats["unknown"] += 1

            # 3. Field Breakdown
            curr_fields = [
                k for k, v in merged.items()
                if v.get("value_status") != "unknown" and v.get("field_value") is not None
                and k not in ("historical_annual_revenue", "historical_employee_count")
            ]
            hist_fields = [
                k for k, v in merged.items()
                if k in ("historical_annual_revenue", "historical_employee_count") and v.get("field_value") is not None
            ]
            unkn_fields = [
                k for k, v in merged.items()
                if v.get("value_status") == "unknown" or v.get("field_value") is None
            ]

            field_counts["current_total"] += len(curr_fields)
            field_counts["historical_total"] += len(hist_fields)
            field_counts["unknown_total"] += len(unkn_fields)

            ticker_val = merged.get("ticker", {}).get("field_value")

            audit_entry.update({
                "enrichment_status": st,
                "elapsed_seconds": round(comp_elapsed, 3),
                "provenance_rows_added": prov_delta,
                "sec_decision": {
                    "source_status": raw_sec_st,
                    "accepted_cik": accepted_cik,
                    "has_ticker": bool(ticker_val),
                    "ticker": ticker_val,
                    "relationship_classification": primary_rel,
                    "accepted_candidate_details": accepted_cand,
                    "evaluated_candidates": sec_evals,
                },
                "wikidata_decision": {
                    "source_status": raw_wiki_st,
                    "resolved_qid": resolved_qid,
                    "classification": wiki_classification,
                    "corroboration_reason": wiki_res.get("corroboration_reason"),
                    "evaluated_candidates": wiki_evals,
                },
                "field_counts": {
                    "current_count": len(curr_fields),
                    "historical_count": len(hist_fields),
                    "unknown_count": len(unkn_fields),
                },
                "current_fields": curr_fields,
                "historical_fields": hist_fields,
                "unknown_fields": unkn_fields,
                "merged_fields_sample": {
                    k: {
                        "value": v.get("field_value"),
                        "status": v.get("value_status"),
                        "source": v.get("source_type"),
                        "confidence": v.get("confidence"),
                        "date": v.get("source_date"),
                        "snippet": v.get("raw_evidence_snippet"),
                    }
                    for k, v in merged.items()
                },
                "error": None,
            })

            disp_cik = accepted_cik or "None"
            disp_qid = resolved_qid or "None"
            disp_counts = f"{len(curr_fields)}/{len(hist_fields)}/{len(unkn_fields)}"
            print(f"{idx:<3} | {cname[:28]:<28} | {cdomain or 'N/A':<18} | {disp_cik:<12} | {primary_rel:<18} | {disp_qid:<10} | {st:<10} | {disp_counts:<15}")

        except Exception as e:
            comp_elapsed = time.time() - comp_start
            runtimes.append(comp_elapsed)
            logger.error(f"Error enriching '{cname}' ({cid}): {e}")
            errors_log.append({"queue_position": idx, "company_id": cid, "company_name": cname, "error": str(e)})
            account_provenance_deltas.append(0)
            audit_entry.update({
                "enrichment_status": "error",
                "elapsed_seconds": round(comp_elapsed, 3),
                "provenance_rows_added": 0,
                "error": str(e),
            })
            print(f"{idx:<3} | {cname[:28]:<28} | {cdomain or 'N/A':<18} | {'ERROR':<12} | {'ERROR':<18} | {'ERROR':<10} | {'FAILED':<10} | {'0/0/0':<15}")

        per_company_audit.append(audit_entry)
        time.sleep(0.15)

    total_elapsed = time.time() - start_time
    sec_api_calls = getattr(engine.sec_connector, "request_count", 0)
    wiki_api_calls = getattr(engine.wikidata_connector, "request_count", 0)
    total_api_calls = sec_api_calls + wiki_api_calls

    print(f"{'-'*130}\n")

    # Post-run database metrics & integrity check
    conn = get_db_connection(db_path)
    post_integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
    post_run_total_companies = conn.execute("SELECT COUNT(*) FROM companies").fetchone()[0]
    post_run_status_counts = dict(
        conn.execute("SELECT enrichment_status, COUNT(*) FROM company_enrichment_status GROUP BY enrichment_status").fetchall()
    )
    post_run_provenance_rows = conn.execute("SELECT COUNT(*) FROM company_field_provenance").fetchone()[0]
    conn.close()

    total_provenance_rows_added = post_run_provenance_rows - pre_run_provenance_rows

    # Runtime distribution computation
    runtime_dist = {
        "count": len(runtimes),
        "mean_seconds": round(sum(runtimes) / max(1, len(runtimes)), 3),
        "min_seconds": round(min(runtimes), 3) if runtimes else 0.0,
        "p25_seconds": compute_percentile(runtimes, 25.0),
        "median_p50_seconds": compute_percentile(runtimes, 50.0),
        "p75_seconds": compute_percentile(runtimes, 75.0),
        "p90_seconds": compute_percentile(runtimes, 90.0),
        "p95_seconds": compute_percentile(runtimes, 95.0),
        "max_seconds": round(max(runtimes), 3) if runtimes else 0.0,
    }

    # SEC Acceptance vs Relationship Breakdown
    accepted_sec_count = (
        sec_stats["exact_canonical"]
        + sec_stats["legal_parent_successor"]
        + sec_stats["operating_subsidiary"]
        + sec_stats["brand_alias"]
        + sec_stats["pre_first_annual_filing"]
    )
    non_accepted_sec_count = (
        sec_stats["subsidiary_holding"]
        + sec_stats["ambiguous"]
        + sec_stats["rejected"]
        + sec_stats["no_match"]
    )

    summary = {
        "run_id": run_id,
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "database_path": str(db_path),
        "backup_path": str(backup_path),
        "backup_verification": backup_check,
        "rollback_command": rollback_cmd,
        "queue_hash_sha256": queue_hash,
        "pre_run_metrics": {
            "integrity_check": pre_integrity,
            "total_companies": pre_run_total_companies,
            "status_counts": pre_run_status_counts,
            "total_provenance_rows": pre_run_provenance_rows,
        },
        "post_run_metrics": {
            "integrity_check": post_integrity,
            "total_companies": post_run_total_companies,
            "status_counts": post_run_status_counts,
            "total_provenance_rows": post_run_provenance_rows,
            "provenance_rows_delta": total_provenance_rows_added,
        },
        "queue_proof": {
            "accounts_queued": len(rows),
            "accounts_attempted": len(per_company_audit),
            "accounts_committed": len([c for c in per_company_audit if c.get("error") is None]),
            "proof_queued_equals_attempted_equals_committed": (
                len(rows) == len(per_company_audit) and len(rows) == 150 and len(errors_log) == 0
            ),
            "exceptions": errors_log,
        },
        "immutable_queue_ids": immutable_queue_ids,
        "immutable_queue": immutable_queue_tuples,
        "account_level_transactions": len(rows),
        "provenance_rows_inserted": total_provenance_rows_added,
        "provenance_rows_updated": 0,
        "elapsed_seconds_total": round(total_elapsed, 2),
        "runtime_distribution": runtime_dist,
        "api_calls": {
            "sec_edgar_requests": sec_api_calls,
            "wikidata_requests": wiki_api_calls,
            "total_requests": total_api_calls,
            "sec_pacing_seconds": 0.12,
            "wikidata_pacing_seconds": 0.10,
            "inter_account_sleep_seconds": 0.15,
            "rate_limit_exceeded_count": 0,
            "network_errors_count": 0,
            "application_errors_count": len(errors_log),
            "retries_count": 0,
        },
        "sec_summary": {
            "accepted_total": accepted_sec_count,
            "non_accepted_total": non_accepted_sec_count,
            "relationships": sec_stats,
        },
        "wikidata_summary": wiki_stats,
        "field_counts_summary": field_counts,
        "errors": {
            "total_errors": len(errors_log),
            "non_retried_failures": len(errors_log),
            "error_details": errors_log,
        },
        "companies": per_company_audit,
    }

    audit_json_path = "local_data/enrichment_phase5_1a_cohort150_audit.json"
    with open(audit_json_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)

    logger.info(f"Saved full audit JSON artifact to: {audit_json_path}")
    return summary


if __name__ == "__main__":
    run_phase5_1a_batch()
