"""
Company Enrichment Engine & Orchestrator (Phase 4 Foundation)
EON Commercial Intelligence | External Review Build

Coordinates free-source connectors (SEC EDGAR & Wikidata) to populate
company firmographics and statutory intelligence with zero-cost services.

Enrichment Workflow Priority:
1. Immediate enrichment on single-company creation or user 'Enrich Now' action
2. Top-ranked companies first (priority_tier = 1)
3. Background backfill for remaining portfolio companies (priority_tier = 2)

Conflict Resolution Hierarchy:
- Tier 1: SEC EDGAR (Statutory Government Filing) -> Authoritative for CIK, SIC, ticker, exchange, statutory address
- Tier 2: Wikidata (Structured Semantic Graph) -> Authoritative for founding year, employee counts, revenue, QID
- Invariant: Never invent values. Explicitly record 'unknown' for absent fields.
"""

import datetime
from datetime import datetime, timezone
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from dashboard.company_db import (
    get_db_connection,
    get_company_field_provenance,
    upsert_field_provenance_records,
    update_enrichment_status,
)
from dashboard.enrichment_connectors import SecEdgarConnector, WikidataConnector

logger = logging.getLogger("eon.enrichment.engine")

# Core firmographic fields evaluated for 'complete' vs 'partial' status
CORE_FIELDS = {
    "sec_cik",
    "ticker",
    "sic_code",
    "sic_description",
    "headquarters_city",
    "wikidata_qid",
    "founded_year",
    "employee_count",
    "annual_revenue",
    "official_website",
}


class CompanyEnrichmentEngine:
    """
    Central orchestration engine for company intelligence enrichment.
    """

    def __init__(
        self,
        db_path: Optional[Union[str, Path]] = None,
        sec_connector: Optional[SecEdgarConnector] = None,
        wikidata_connector: Optional[WikidataConnector] = None,
    ):
        self.db_path = db_path
        self.sec_connector = sec_connector or SecEdgarConnector()
        self.wikidata_connector = wikidata_connector or WikidataConnector()

    def enrich_company_by_id(
        self,
        company_id: str,
        force: bool = False,
    ) -> Dict[str, Any]:
        """
        Enriches a company by company_id.
        Fetches SEC EDGAR and Wikidata, resolves conflicts, stores provenance,
        and transitions status: partial, complete, failed.
        """
        conn = get_db_connection(self.db_path)
        comp = conn.execute(
            "SELECT company_id, company_name, domain FROM companies WHERE company_id = ?",
            (company_id,),
        ).fetchone()

        if not comp:
            return {"success": False, "error": f"Company ID '{company_id}' not found."}

        company_name = comp["company_name"]
        domain = comp["domain"]
        now_iso = datetime.now(timezone.utc).isoformat()

        # Step 1: Call SEC EDGAR
        sec_result = self.sec_connector.enrich_company(company_name=company_name, domain=domain)
        sec_status = sec_result.get("source_status", "error")
        sec_cik = sec_result.get("cik")
        sec_ticker = None
        for f in sec_result.get("fields", []):
            if f.get("field_name") == "ticker" and f.get("field_value"):
                sec_ticker = str(f["field_value"]).split(",")[0].strip()
                break

        # Step 2: Call Wikidata with conservative corroboration (Domain, CIK, Ticker)
        wiki_result = self.wikidata_connector.enrich_company(
            company_name=company_name,
            domain=domain,
            ticker=sec_ticker,
            cik=sec_cik,
        )
        wiki_status = wiki_result.get("source_status", "error")

        # Step 3: Conflict Resolution & Field Merging
        merged_fields: Dict[str, Dict[str, Any]] = {}

        # Load SEC EDGAR fields (Tier 1 Authority)
        for f in sec_result.get("fields", []):
            fname = f["field_name"]
            merged_fields[fname] = f

        # Load Wikidata fields (Tier 2 Authority)
        for f in wiki_result.get("fields", []):
            fname = f["field_name"]
            if fname not in merged_fields:
                merged_fields[fname] = f
            else:
                # Conflict resolution: SEC EDGAR takes precedence for statutory fields
                if f.get("value_status") != "unknown" and merged_fields[fname].get("value_status") == "unknown":
                    merged_fields[fname] = f

        # Step 4: Ensure all CORE_FIELDS have explicit records (Unknown is allowed and recorded)
        for core_field in CORE_FIELDS:
            if core_field not in merged_fields:
                merged_fields[core_field] = {
                    "field_name": core_field,
                    "field_value": None,
                    "value_status": "unknown",
                    "source_url": None,
                    "source_type": "none",
                    "source_date": now_iso[:10],
                    "confidence": "UNVERIFIED",
                    "raw_evidence_snippet": f"Not found in SEC EDGAR or Wikidata records for {company_name}.",
                }

        # Step 5: Save Field Provenance to SQLite
        provenance_list = list(merged_fields.values())
        upsert_field_provenance_records(company_id, provenance_list, self.db_path)

        # Step 6: Determine Final Enrichment Status
        valid_enriched = [f for f in provenance_list if f.get("value_status") != "unknown" and f.get("field_value") is not None]

        if sec_status == "error" and wiki_status == "error":
            final_status = "failed"
            error_msg = "Both SEC EDGAR and Wikidata connectors encountered errors."
        elif len(valid_enriched) >= 4:
            final_status = "complete"
            error_msg = None
        elif len(valid_enriched) > 0:
            final_status = "partial"
            error_msg = None
        else:
            final_status = "partial"
            error_msg = "No authoritative public records found on SEC EDGAR or Wikidata."

        update_enrichment_status(
            company_id=company_id,
            status=final_status,
            sec_status=sec_status,
            wikidata_status=wiki_status,
            error_message=error_msg,
            db_path=self.db_path,
        )

        return {
            "success": True,
            "company_id": company_id,
            "company_name": company_name,
            "enrichment_status": final_status,
            "fields_enriched_count": len(valid_enriched),
            "fields_total": len(provenance_list),
            "sec_status": sec_status,
            "wikidata_status": wiki_status,
            "sec_result": sec_result,
            "wiki_result": wiki_result,
            "merged_fields": merged_fields,
        }

    def enrich_top_ranked_companies(self, limit: int = 10) -> List[Dict[str, Any]]:
        """
        Enriches top-ranked / prioritized companies first (Workflow step 1).
        Prioritizes priority_tier = 1 (direct adds / top ranked) and not_started / stale status.
        """
        conn = get_db_connection(self.db_path)
        rows = conn.execute(
            """
            SELECT c.company_id
            FROM companies c
            JOIN company_enrichment_status s ON c.company_id = s.company_id
            WHERE s.enrichment_status IN ('not_started', 'stale')
            ORDER BY s.priority_tier ASC, c.source_tier ASC, c.id ASC
            LIMIT ?;
            """,
            (limit,),
        ).fetchall()

        results = []
        for r in rows:
            res = self.enrich_company_by_id(r["company_id"])
            results.append(res)
        return results

    def backfill_remaining_companies(self, limit: int = 50) -> List[Dict[str, Any]]:
        """
        Background backfill for remaining universe companies (Workflow step 2).
        Processes not_started companies in batches.
        """
        conn = get_db_connection(self.db_path)
        rows = conn.execute(
            """
            SELECT c.company_id
            FROM companies c
            JOIN company_enrichment_status s ON c.company_id = s.company_id
            WHERE s.enrichment_status = 'not_started'
            ORDER BY c.id ASC
            LIMIT ?;
            """,
            (limit,),
        ).fetchall()

        results = []
        for r in rows:
            res = self.enrich_company_by_id(r["company_id"])
            results.append(res)
        return results

    def remediate_company_identity(
        self,
        company_id: str,
        reason: str,
        reviewer_decision: str = "REJECTED_FALSE_POSITIVE",
        commit_or_version: str = "phase5_1a_remediation",
    ) -> Dict[str, Any]:
        """
        Documented application-level remediation/re-enrichment mechanism.
        Remediates an erroneous statutory identity mapping:
        1. Audits prior state (old CIK, old registrant, old relationship snippet).
        2. Sets all SEC-derived fields from the rejected CIK to explicit Unknown / superseded status.
        3. Preserves non-SEC fields whose provenance is independent of the rejected CIK.
        4. Re-enriches the entity through the hardened connectors in forced mode.
        5. Preserves and returns an immutable remediation audit record.
        """
        conn = get_db_connection(self.db_path)
        conn.row_factory = None
        comp = conn.execute(
            "SELECT company_id, company_name, domain FROM companies WHERE company_id = ?",
            (company_id,),
        ).fetchone()
        if not comp:
            conn.close()
            return {"success": False, "error": f"Company ID '{company_id}' not found."}

        company_name, domain = comp[1], comp[2]

        # Audit prior SEC provenance
        prov_rows = conn.execute(
            "SELECT field_name, field_value, value_status, source_type, raw_evidence_snippet FROM company_field_provenance WHERE company_id = ?",
            (company_id,),
        ).fetchall()
        conn.close()

        old_cik = None
        old_snippet = None
        for r in prov_rows:
            if r[0] == "sec_cik" and r[1]:
                old_cik = r[1]
                old_snippet = r[4]
                break

        old_registrant = None
        if old_snippet and "WEST PHARMACEUTICAL" in old_snippet.upper():
            old_registrant = "WEST PHARMACEUTICAL SERVICES INC"
        elif old_cik:
            old_registrant = f"CIK {old_cik} registrant"

        now_iso = datetime.now(timezone.utc).isoformat()

        # Step 1: Invalidate SEC-derived fields in provenance
        sec_fields_to_invalidate = [
            "sec_cik", "ticker", "exchange", "sic_code", "sic_description",
            "incorporation_state", "fiscal_year_end", "headquarters_city",
            "headquarters_state", "latest_annual_filing_date"
        ]

        invalidated_provenance = []
        for fname in sec_fields_to_invalidate:
            invalidated_provenance.append({
                "field_name": fname,
                "field_value": None,
                "value_status": "unknown",
                "source_url": "https://www.sec.gov/edgar/searchedgar/companysearch",
                "source_type": "sec_edgar",
                "source_date": now_iso[:10],
                "confidence": "UNVERIFIED",
                "raw_evidence_snippet": (
                    f"Remediated: CIK {old_cik or 'unknown'} revoked ({reason}). "
                    f"Reviewer decision: {reviewer_decision} at {now_iso}."
                ),
            })

        upsert_field_provenance_records(company_id, invalidated_provenance, self.db_path)

        # Step 2: Force re-enrichment through the hardened connectors
        re_enrich_result = self.enrich_company_by_id(company_id, force=True)

        remediation_record = {
            "company_id": company_id,
            "company_name": company_name,
            "domain": domain,
            "old_cik": old_cik,
            "old_registrant": old_registrant,
            "old_relationship_snippet": old_snippet,
            "corrected_status": re_enrich_result.get("enrichment_status"),
            "corrected_sec_cik": re_enrich_result.get("merged_fields", {}).get("sec_cik", {}).get("field_value"),
            "timestamp_utc": now_iso,
            "code_version": commit_or_version,
            "reason": reason,
            "reviewer_decision": reviewer_decision,
            "re_enrichment_result": re_enrich_result,
        }

        return remediation_record
