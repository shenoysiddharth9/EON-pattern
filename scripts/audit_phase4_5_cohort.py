"""
Phase 4.5 Validation Audit Script (Deterministic Dry-Run, No DB Writes)
Audits the 15-company cohort with the hardened SEC Entity-Identity Resolver
and Current-Operating-Entity Gate.
"""

from datetime import datetime, timezone
import json
import logging
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from dashboard.enrichment_connectors import SecEdgarConnector

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("eon.phase4_5.audit")

COHORT_COMPANIES = [
    {"name": "EnQuest", "domain": "enquest.com"},
    {"name": "Eni", "domain": "eni.com"},
    {"name": "Talos Energy", "domain": "talosenergy.com"},
    {"name": "Abu Dhabi National Oil Company", "domain": "adnoc.ae"},
    {"name": "ExxonMobil", "domain": "exxonmobil.com"},
    {"name": "Kinder Morgan", "domain": "kindermorgan.com"},
    {"name": "Roehm", "domain": "roehm.com"},
    {"name": "Subsea7", "domain": "subsea7.com"},
    {"name": "HEISCO", "domain": "heisco.com"},
    {"name": "McDermott", "domain": "mcdermott.com"},
    {"name": "ONEOK", "domain": "oneok.com"},
    {"name": "PETRONAS", "domain": "petronas.com"},
    {"name": "Pertamina", "domain": "pertamina.com"},
    {"name": "QatarEnergy", "domain": "qatarenergy.qa"},
    {"name": "Saipem", "domain": "saipem.com"},
]


def run_audit(output_json_path: str = "local_data/enrichment_phase4_5_validation_audit.json") -> dict:
    connector = SecEdgarConnector()
    results = []

    print(f"\n{'='*115}")
    print(f"{'PHASE 4.5 SEC RESOLUTION & CURRENT-OPERATING-ENTITY VALIDATION AUDIT (15 ACCOUNTS)':^115}")
    print(f"{'='*115}")
    print(f"{'#':<3} | {'Target Company':<28} | {'Supplied Domain':<18} | {'Accepted CIK':<12} | {'Accepted Issuer Name':<24} | {'Latest 10-K/20-F':<15}")
    print(f"{'-'*115}")

    for idx, item in enumerate(COHORT_COMPANIES, 1):
        target_name = item["name"]
        domain = item["domain"]

        enrich_res = connector.enrich_company(company_name=target_name, domain=domain)
        source_status = enrich_res.get("source_status")
        accepted_cik = enrich_res.get("cik")
        eval_cands = enrich_res.get("evaluated_candidates", [])
        fields = enrich_res.get("fields", [])

        accepted_name = None
        accepted_annual_date = None
        accepted_has_current = False

        fields_dict = {}
        for f in fields:
            fields_dict[f["field_name"]] = {
                "value": f["field_value"],
                "status": f["value_status"],
                "confidence": f["confidence"],
                "snippet": f.get("raw_evidence_snippet"),
            }

        if accepted_cik:
            for c in eval_cands:
                if c.get("cik") == accepted_cik:
                    accepted_name = c.get("registrant_name")
                    accepted_annual_date = c.get("latest_annual_filing_date")
                    accepted_has_current = c.get("has_current_operating_filings", False)
                    break
            if not accepted_annual_date and "latest_annual_filing_date" in fields_dict:
                accepted_annual_date = fields_dict["latest_annual_filing_date"]["value"]

        # Audit entry
        audit_entry = {
            "index": idx,
            "target_company_name": target_name,
            "supplied_domain": domain,
            "sec_source_status": source_status,
            "accepted_cik": accepted_cik,
            "accepted_registrant_name": accepted_name,
            "accepted_has_current_operating_filings": accepted_has_current,
            "accepted_latest_annual_filing_date": accepted_annual_date,
            "total_candidates_evaluated": len(eval_cands),
            "candidates_evaluated": eval_cands,
            "produced_fields": fields_dict,
        }
        results.append(audit_entry)

        display_cik = accepted_cik or "None (Unknown)"
        display_name = (accepted_name[:22] + "..") if (accepted_name and len(accepted_name) > 24) else (accepted_name or "N/A")
        display_date = accepted_annual_date or "N/A"
        print(f"{idx:<3} | {target_name:<28} | {domain:<18} | {display_cik:<12} | {display_name:<24} | {display_date:<15}")

    print(f"{'='*115}\n")

    summary = {
        "audit_name": "Phase 4.5 SEC Entity-Resolution & Current-Operating-Entity Gate Validation",
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "total_accounts": len(results),
        "accepted_canonical_count": sum(1 for r in results if r["accepted_cik"] is not None),
        "explicit_unknown_count": sum(1 for r in results if r["accepted_cik"] is None),
        "database_writes": 0,
        "results": results,
    }

    os.makedirs(os.path.dirname(output_json_path), exist_ok=True)
    with open(output_json_path, "w") as f:
        json.dump(summary, f, indent=2)

    logger.info(f"Saved audit output to {output_json_path}")
    return summary


if __name__ == "__main__":
    run_audit()
