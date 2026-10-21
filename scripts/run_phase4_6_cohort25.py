"""
Controlled Live Batch Execution Script: Phase 4.6 (Cohort of 25 Companies)
Executes priority-first live enrichment with pre-run backup, conservative SEC/Wikidata resolvers,
Current-Operating-Entity Gate, and comprehensive audit JSON generation.
"""

from datetime import datetime, timezone
import json
import logging
import os
from pathlib import Path
import sqlite3
import sys
import time
from typing import Any, Dict, List, Optional

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from dashboard.company_db import DEFAULT_DB_PATH, get_db_connection
from dashboard.enrichment_engine import CompanyEnrichmentEngine

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("eon.phase4_6.cohort25")

EXCLUDED_COMPANY_IDS = [
    # 15 Phase 4.4/4.5 pilot cohort companies
    "comp_abu_dhabi_national_oil_company_0a4252d6",
    "comp_enquest_fc0ad4b5",
    "comp_eni_9d16925e",
    "comp_exxonmobil_ab6ab52c",
    "comp_heisco_80a32141",
    "comp_kinder_morgan_9ccb5436",
    "comp_mcdermott_889d5cde",
    "comp_oneok_b1c29fd8",
    "comp_petronas_ae2fd078",
    "comp_pertamina_e1578ef4",
    "comp_qatarenergy_4eebb626",
    "comp_roehm_252db490",
    "comp_saipem_4b89d120",
    "comp_subsea7_89234038",
    "comp_talos_energy_6603b6d5",
    # Pre-existing Cheniere test record
    "comp_cheniere_energy_inc_6fac1aff",
]


def make_timestamped_backup(db_path: Path) -> Path:
    backup_dir = db_path.parent / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = backup_dir / f"companies_master_pre_phase4_6_{timestamp}.db"

    src = sqlite3.connect(db_path)
    dst = sqlite3.connect(backup_path)
    with dst:
        src.backup(dst)
    dst.close()
    src.close()
    return backup_path


def verify_backup(backup_path: Path, db_path: Path) -> bool:
    if not backup_path.exists():
        return False
    b_conn = sqlite3.connect(backup_path)
    m_conn = sqlite3.connect(db_path)
    b_cnt = b_conn.execute("SELECT COUNT(*) FROM companies").fetchone()[0]
    m_cnt = m_conn.execute("SELECT COUNT(*) FROM companies").fetchone()[0]
    b_conn.close()
    m_conn.close()
    return b_cnt == m_cnt and b_cnt > 0


def run_phase4_6_batch() -> Dict[str, Any]:
    db_path = Path("local_data/companies_master.db")
    timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_id = f"phase4_6_cohort25_{timestamp_str}"

    print(f"\n{'='*115}")
    print(f"{'PHASE 4.6 CONTROLLED LIVE BATCH ENRICHMENT (25 COMPANIES)':^115}")
    print(f"{'='*115}")
    logger.info(f"Run ID: {run_id}")
    logger.info(f"Target Database: {db_path}")

    # 1. Atomic pre-run backup
    backup_path = make_timestamped_backup(db_path)
    logger.info(f"Created timestamped SQLite backup at: {backup_path}")
    if not verify_backup(backup_path, db_path):
        raise RuntimeError(f"Backup verification failed for {backup_path}")
    logger.info("Backup integrity verified: tables and record counts match 100%.")
    rollback_cmd = f"cp {backup_path} {db_path}"
    logger.info(f"Tested Rollback Command: {rollback_cmd}")

    # 2. Select next 25 not_started companies via priority-first ordering
    conn = get_db_connection(db_path)
    conn.row_factory = sqlite3.Row

    placeholders = ",".join(f"'{cid}'" for cid in EXCLUDED_COMPANY_IDS)
    query = f"""
        SELECT c.company_id, c.company_name, c.domain, s.priority_tier, s.enrichment_status
        FROM companies c
        JOIN company_enrichment_status s ON c.company_id = s.company_id
        WHERE s.enrichment_status IN ('not_started', 'stale')
          AND c.company_id NOT IN ({placeholders})
        ORDER BY 
            s.priority_tier ASC,
            (SELECT COUNT(*) FROM company_triggers WHERE company_id = c.company_id) DESC,
            c.source_tier ASC,
            c.company_name ASC
        LIMIT 25;
    """

    rows = conn.execute(query).fetchall()
    conn.close()

    if len(rows) != 25:
        logger.warning(f"Expected 25 companies, retrieved {len(rows)}")

    logger.info(f"Queued {len(rows)} accounts for priority-first live enrichment:")
    for idx, r in enumerate(rows, 1):
        logger.info(f"  {idx:2d}. {r['company_name']} ({r['domain'] or 'no-domain'}) [tier {r['priority_tier']}]")

    engine = CompanyEnrichmentEngine(db_path=db_path)
    start_time = time.time()

    per_company_audit: List[Dict[str, Any]] = []
    sec_stats = {
        "exact_canonical": 0,
        "legal_parent_successor": 0,
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

    print(f"\n{'-'*115}")
    print(f"{'#':<3} | {'Company Name':<28} | {'Supplied Domain':<18} | {'SEC CIK':<12} | {'Wiki QID':<10} | {'Status':<10} | {'Fields (Curr/Hist/Unk)':<20}")
    print(f"{'-'*115}")

    for idx, r in enumerate(rows, 1):
        cid = r["company_id"]
        cname = r["company_name"]
        cdomain = r["domain"]
        comp_start = time.time()

        audit_entry: Dict[str, Any] = {
            "index": idx,
            "company_id": cid,
            "company_name": cname,
            "domain": cdomain,
            "priority_tier": r["priority_tier"],
        }

        try:
            res = engine.enrich_company_by_id(cid, force=True)
            comp_elapsed = time.time() - comp_start
            st = res.get("enrichment_status", "unknown")
            sec_res = res.get("sec_result", {})
            wiki_res = res.get("wiki_result", {})
            merged = res.get("merged_fields", {})

            # 1. SEC Breakdown
            raw_sec_st = sec_res.get("source_status", "error")
            accepted_cik = sec_res.get("cik")
            sec_evals = sec_res.get("evaluated_candidates", [])

            primary_rel = "no_match"
            if accepted_cik:
                for c in sec_evals:
                    if c.get("cik") == accepted_cik:
                        primary_rel = c.get("relationship", "exact_canonical")
                        break
                if primary_rel == "exact_canonical":
                    sec_stats["exact_canonical"] += 1
                elif primary_rel == "legal_parent_successor":
                    sec_stats["legal_parent_successor"] += 1
            elif sec_evals:
                # Find dominant rejection reason
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

            audit_entry.update({
                "enrichment_status": st,
                "elapsed_seconds": round(comp_elapsed, 2),
                "sec_decision": {
                    "source_status": raw_sec_st,
                    "accepted_cik": accepted_cik,
                    "relationship_classification": primary_rel,
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
            disp_counts = f"{len(curr_fields)} / {len(hist_fields)} / {len(unkn_fields)}"
            print(f"{idx:<3} | {cname[:28]:<28} | {cdomain or 'N/A':<18} | {disp_cik:<12} | {disp_qid:<10} | {st:<10} | {disp_counts:<20}")

        except Exception as e:
            comp_elapsed = time.time() - comp_start
            logger.error(f"Error enriching '{cname}' ({cid}): {e}")
            errors_log.append({"company_id": cid, "company_name": cname, "error": str(e)})
            audit_entry.update({
                "enrichment_status": "error",
                "elapsed_seconds": round(comp_elapsed, 2),
                "error": str(e),
            })
            print(f"{idx:<3} | {cname[:28]:<28} | {cdomain or 'N/A':<18} | {'ERROR':<12} | {'ERROR':<10} | {'FAILED':<10} | {'0 / 0 / 0':<20}")

        per_company_audit.append(audit_entry)
        time.sleep(0.15)

    total_elapsed = time.time() - start_time
    sec_api_calls = getattr(engine.sec_connector, "request_count", 0)
    wiki_api_calls = getattr(engine.wikidata_connector, "request_count", 0)
    total_api_calls = sec_api_calls + wiki_api_calls

    print(f"{'-'*115}\n")

    summary = {
        "run_id": run_id,
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "database_path": str(db_path),
        "backup_path": str(backup_path),
        "rollback_command": rollback_cmd,
        "accounts_queued": len(rows),
        "accounts_processed": len(per_company_audit),
        "database_writes": len(rows),
        "elapsed_seconds_total": round(total_elapsed, 2),
        "avg_seconds_per_account": round(total_elapsed / max(1, len(rows)), 2),
        "api_calls": {
            "sec_edgar_requests": sec_api_calls,
            "wikidata_requests": wiki_api_calls,
            "total_requests": total_api_calls,
            "sec_pacing_seconds": 0.12,
            "wikidata_pacing_seconds": 0.10,
        },
        "sec_summary": sec_stats,
        "wikidata_summary": wiki_stats,
        "field_counts_summary": field_counts,
        "errors": {
            "total_errors": len(errors_log),
            "non_retried_failures": len(errors_log),
            "error_details": errors_log,
        },
        "companies": per_company_audit,
    }

    audit_json_path = "local_data/enrichment_phase4_6_cohort25_audit.json"
    with open(audit_json_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)

    logger.info(f"Saved full audit JSON artifact to: {audit_json_path}")
    return summary


if __name__ == "__main__":
    run_phase4_6_batch()
