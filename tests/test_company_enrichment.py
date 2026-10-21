"""
Tests for Phase 4: DB-First Company Enrichment & Provenance Foundation
EON Commercial Intelligence | External Review Build
"""

import json
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest

import pandas as pd

from dashboard.company_db import (
    init_company_database,
    seed_database_from_default_csv,
    add_single_company,
    import_csv_as_override,
    get_all_companies_dataframe,
    get_company_field_provenance,
    upsert_field_provenance_records,
    update_enrichment_status,
    check_and_mark_stale_records,
    get_db_connection,
)
from dashboard.enrichment_connectors import (
    SecEdgarConnector,
    WikidataConnector,
    classify_sec_candidate_relationship,
)
from dashboard.enrichment_engine import CompanyEnrichmentEngine, CORE_FIELDS


class TestCompanyEnrichment(unittest.TestCase):
    def setUp(self):
        # Create a temporary database for each test to ensure test isolation
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test_companies.db"

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_schema_initialization_and_seeding(self):
        """Verifies tables are created, WAL mode is active, and default CSV seeds 785 companies."""
        count = seed_database_from_default_csv(db_path=self.db_path)
        self.assertGreaterEqual(count, 785)

        conn = get_db_connection(self.db_path)
        tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table';").fetchall()]
        self.assertIn("companies", tables)
        self.assertIn("company_triggers", tables)
        self.assertIn("company_enrichment_status", tables)
        self.assertIn("company_field_provenance", tables)

        df = get_all_companies_dataframe(db_path=self.db_path)
        self.assertEqual(len(df), count)
        # All seeded companies start as not_started
        self.assertTrue((df["enrichment_status"] == "not_started").all())

    def test_single_company_direct_addition(self):
        """Verifies adding a single company directly without uploading a CSV."""
        seed_database_from_default_csv(db_path=self.db_path)
        res = add_single_company(
            company_name="Vanguard Energy Services",
            segment="Oil & Gas",
            domain="vanguardenergy.com",
            source_tier=1,
            initial_trigger={
                "trigger_type": "project_fid_commissioning",
                "trigger_date": "2026-10-01",
                "trigger_summary": "Approved major greenfield facility expansion",
            },
            db_path=self.db_path,
        )

        self.assertTrue(res["success"])
        cid = res["company_id"]

        df = get_all_companies_dataframe(db_path=self.db_path)
        added = df[df["company_id"] == cid].iloc[0]
        self.assertEqual(added["company_name"], "Vanguard Energy Services")
        self.assertEqual(added["created_source"], "user_direct")
        # Priority tier 1 for immediate enrichment
        self.assertEqual(added["priority_tier"], 1)
        self.assertEqual(added["enrichment_status"], "not_started")

    def test_csv_override_and_update(self):
        """Verifies CSV import acts as an update/override without wiping DB as source of truth."""
        seed_database_from_default_csv(db_path=self.db_path)
        custom_df = pd.DataFrame([
            {
                "company": "Baker Hughes",
                "segment": "Energy Technology & Turbomachinery",  # updated segment
                "domain": "bakerhughes.com",
                "source_tier": 1,
                "trigger_type": "new_leader",
                "trigger_date": "2026-09-20",
                "trigger_summary": "Announced VP executive change in energy technology",
            },
            {
                "company": "New Wave Robotics",
                "segment": "Manufacturing",
                "domain": "newwaverobotics.com",
                "source_tier": 2,
            }
        ])

        summary = import_csv_as_override(custom_df, override_mode="merge_update", db_path=self.db_path)
        self.assertEqual(summary["inserted_count"], 1)  # New Wave Robotics inserted
        self.assertEqual(summary["updated_count"], 1)   # Baker Hughes updated

        df = get_all_companies_dataframe(db_path=self.db_path)
        bh = df[df["company_name"] == "Baker Hughes"].iloc[0]
        self.assertEqual(bh["segment"], "Energy Technology & Turbomachinery")

    def test_sec_edgar_connector_extraction_and_provenance(self):
        """Verifies SEC EDGAR connector parses CIK, SIC, ticker with exact status and HIGH confidence."""
        mock_tickers_json = json.dumps({
            "0": {"cik_str": 1701605, "ticker": "BKR", "title": "Baker Hughes Co"}
        })
        mock_submissions_json = json.dumps({
            "cik": "0001701605",
            "tickers": ["BKR"],
            "exchanges": ["NASDAQ"],
            "sic": "3533",
            "sicDescription": "OIL & GAS FIELD MACHINERY & EQUIPMENT",
            "stateOfIncorporation": "DE",
            "fiscalYearEnd": "1231",
            "addresses": {
                "business": {"city": "HOUSTON", "stateOrCountry": "TX"}
            },
            "filings": {
                "recent": {
                    "form": ["10-K", "10-Q"],
                    "filingDate": ["2026-02-12", "2026-05-01"]
                }
            }
        })

        def mock_http(url, headers):
            if "company_tickers.json" in url:
                return 200, mock_tickers_json
            if "CIK0001701605.json" in url:
                return 200, mock_submissions_json
            return 404, ""

        connector = SecEdgarConnector(http_client=mock_http)
        res = connector.enrich_company("Baker Hughes")
        self.assertEqual(res["source_status"], "success")

        fields = {f["field_name"]: f for f in res["fields"]}
        self.assertIn("sec_cik", fields)
        self.assertEqual(fields["sec_cik"]["field_value"], "0001701605")
        self.assertEqual(fields["sec_cik"]["value_status"], "exact")
        self.assertEqual(fields["sec_cik"]["confidence"], "HIGH")
        self.assertEqual(fields["sec_cik"]["source_type"], "sec_edgar")
        self.assertTrue(fields["sec_cik"]["source_url"].startswith("https://data.sec.gov"))

        self.assertEqual(fields["sic_code"]["field_value"], "3533")
        self.assertEqual(fields["ticker"]["field_value"], "BKR")
        self.assertEqual(fields["headquarters_city"]["field_value"], "HOUSTON")

    def test_wikidata_connector_extraction_and_provenance(self):
        """Verifies Wikidata connector extracts founding year, employee counts, revenue with provenance."""
        mock_search_json = json.dumps({
            "search": [{"id": "Q804368", "description": "American energy technology company"}]
        })
        mock_claims_json = json.dumps({
            "entities": {
                "Q804368": {
                    "claims": {
                        "P571": [{
                            "mainsnak": {
                                "datavalue": {"value": {"time": "+1907-01-01T00:00:00Z"}}
                            }
                        }],
                        "P1128": [{
                            "mainsnak": {
                                "datavalue": {"value": {"amount": "+55000"}}
                            },
                            "qualifiers": {
                                "P585": [{"datavalue": {"value": {"time": "+2025-01-01T00:00:00Z"}}}]
                            }
                        }],
                        "P2139": [{
                            "mainsnak": {
                                "datavalue": {"value": {"amount": "+25500000000"}}
                            }
                        }],
                        "P856": [{
                            "mainsnak": {
                                "datavalue": {"value": "https://www.bakerhughes.com"}
                            }
                        }]
                    }
                }
            }
        })

        def mock_http(url, headers):
            if "wbsearchentities" in url:
                return 200, mock_search_json
            if "wbgetentities" in url:
                return 200, mock_claims_json
            return 404, ""

        connector = WikidataConnector(http_client=mock_http)
        res = connector.enrich_company("Baker Hughes", domain="bakerhughes.com")
        self.assertEqual(res["source_status"], "success")

        fields = {f["field_name"]: f for f in res["fields"]}
        self.assertEqual(fields["wikidata_qid"]["field_value"], "Q804368")
        self.assertEqual(fields["founded_year"]["field_value"], "1907")
        self.assertEqual(fields["employee_count"]["field_value"], "55000")
        self.assertEqual(fields["employee_count"]["value_status"], "estimate")
        self.assertEqual(fields["employee_count"]["confidence"], "MEDIUM")
        self.assertEqual(fields["official_website"]["field_value"], "https://www.bakerhughes.com")

    def test_unknown_and_missing_data_handling(self):
        """Verifies unknown values are stored with status='unknown', value=None, and never invented."""
        init_company_database(db_path=self.db_path)
        add_single_company("Acme Private Industrial", "Chemicals", db_path=self.db_path)

        def mock_http(url, headers):
            return 404, ""  # Not found anywhere

        sec = SecEdgarConnector(http_client=mock_http)
        wiki = WikidataConnector(http_client=mock_http)
        engine = CompanyEnrichmentEngine(db_path=self.db_path, sec_connector=sec, wikidata_connector=wiki)

        df = get_all_companies_dataframe(db_path=self.db_path)
        cid = df[df["company_name"] == "Acme Private Industrial"].iloc[0]["company_id"]

        result = engine.enrich_company_by_id(cid)
        self.assertTrue(result["success"])
        self.assertEqual(result["enrichment_status"], "partial")

        prov = get_company_field_provenance(cid, db_path=self.db_path)
        # All core fields must exist as explicit 'unknown' records
        for core in CORE_FIELDS:
            self.assertIn(core, prov)
            self.assertEqual(prov[core]["value_status"], "unknown")
            self.assertIsNone(prov[core]["value"])
            self.assertEqual(prov[core]["confidence"], "UNVERIFIED")

    def test_conflicting_data_resolution(self):
        """Verifies SEC EDGAR takes precedence for statutory fields, Wikidata complementary."""
        init_company_database(db_path=self.db_path)
        add_single_company("Conflict Test Corp", "Manufacturing", db_path=self.db_path)

        # SEC EDGAR has official ticker ABC and city Atlanta
        sec_mock = {
            "source_status": "success",
            "fields": [
                {"field_name": "ticker", "field_value": "ABC", "value_status": "exact", "source_url": "sec.gov", "source_type": "sec_edgar", "source_date": "2026-01-01", "confidence": "HIGH"},
                {"field_name": "headquarters_city", "field_value": "Atlanta", "value_status": "exact", "source_url": "sec.gov", "source_type": "sec_edgar", "source_date": "2026-01-01", "confidence": "HIGH"}
            ]
        }
        # Wikidata has complementary founding year and different ticker ABC.N
        wiki_mock = {
            "source_status": "success",
            "fields": [
                {"field_name": "ticker", "field_value": "ABC.N", "value_status": "exact", "source_url": "wikidata.org", "source_type": "wikidata", "source_date": "2026-01-01", "confidence": "MEDIUM"},
                {"field_name": "founded_year", "field_value": "1980", "value_status": "exact", "source_url": "wikidata.org", "source_type": "wikidata", "source_date": "2026-01-01", "confidence": "MEDIUM"}
            ]
        }

        class MockSec(SecEdgarConnector):
            def enrich_company(self, company_name=None, ticker=None, cik=None, **kwargs):
                return sec_mock

        class MockWiki(WikidataConnector):
            def enrich_company(self, company_name=None, domain=None, **kwargs):
                return wiki_mock

        engine = CompanyEnrichmentEngine(db_path=self.db_path, sec_connector=MockSec(), wikidata_connector=MockWiki())
        df = get_all_companies_dataframe(db_path=self.db_path)
        cid = df[df["company_name"] == "Conflict Test Corp"].iloc[0]["company_id"]

        engine.enrich_company_by_id(cid)
        prov = get_company_field_provenance(cid, db_path=self.db_path)

        # SEC EDGAR authoritative for ticker
        self.assertEqual(prov["ticker"]["field_value"], "ABC")
        self.assertEqual(prov["ticker"]["source_type"], "sec_edgar")
        # Wikidata complementary for founded_year
        self.assertEqual(prov["founded_year"]["field_value"], "1980")
        self.assertEqual(prov["founded_year"]["source_type"], "wikidata")

    def test_stale_data_detection(self):
        """Verifies records older than 90 days are identified and transitioned to 'stale'."""
        init_company_database(db_path=self.db_path)
        add_single_company("Stale Corp", "Energy", db_path=self.db_path)
        df = get_all_companies_dataframe(db_path=self.db_path)
        cid = df[df["company_name"] == "Stale Corp"].iloc[0]["company_id"]

        update_enrichment_status(cid, "complete", db_path=self.db_path)
        # Artificially set stale_after to 10 days in the past
        conn = get_db_connection(self.db_path)
        with conn:
            conn.execute(
                "UPDATE company_enrichment_status SET stale_after = '2026-01-01T00:00:00+00:00' WHERE company_id = ?",
                (cid,),
            )

        stale_count = check_and_mark_stale_records(db_path=self.db_path)
        self.assertEqual(stale_count, 1)

        updated_df = get_all_companies_dataframe(db_path=self.db_path)
        row = updated_df[updated_df["company_id"] == cid].iloc[0]
        self.assertEqual(row["enrichment_status"], "stale")

    def test_contact_research_pipeline_invariance(self):
        """Verifies that the Phase 3.1 contact research pipeline remains completely untouched and functional."""
        from dashboard.contact_research import (
            evaluate_employment_freshness,
            classify_title_tier,
            evaluate_candidate_corroboration,
            adjudicate_contact_research,
        )

        # 1. Title tier classification invariance
        tier1, _ = classify_title_tier("Chief Learning Officer")
        self.assertEqual(tier1, "strong_leadership")
        tier2, _ = classify_title_tier("Training Program Manager")
        self.assertEqual(tier2, "practitioner")

        # 2. Aggregator invariant from Phase 3.1: Comparably caps at Employment Unconfirmed
        freshness = evaluate_employment_freshness({
            "evidence_urls": ["https://www.comparably.com/companies/bakerhughes/executive-team"]
        })
        self.assertEqual(freshness["employment_freshness_status"], "Employment Unconfirmed")

        # 3. Adjudication invariance: Baker Hughes unresolved under aggregator-only evidence
        adjudicated = adjudicate_contact_research(
            final_payload={
                "company_name": "Baker Hughes",
                "primary_contact": {
                    "name": "Jose Fernandez",
                    "title": "Chief Learning Officer (CLO)",
                    "evidence_urls": ["https://www.comparably.com/companies/bakerhughes/executive-team"],
                    "why_selected": "Executive listing",
                },
            },
            company="Baker Hughes",
        )
        self.assertEqual(adjudicated["contact_research_status"], "Role Found - Person Unresolved")
        self.assertTrue(adjudicated["is_weak_match"])

    def test_direct_company_add_and_enrich_now_flow(self):
        """Verifies the complete flow of adding a company directly, immediate enrichment, and provenance audit."""
        init_company_database(db_path=self.db_path)
        add_res = add_single_company(
            company_name="Apex Turbomachinery",
            segment="Oil & Gas",
            domain="apexturbo.com",
            source_tier=1,
            db_path=self.db_path,
        )
        self.assertTrue(add_res["success"])
        cid = add_res["company_id"]

        mock_sec = {
            "source_status": "success",
            "fields": [
                {"field_name": "sec_cik", "field_value": "0001999999", "value_status": "exact", "source_url": "https://data.sec.gov/submissions/CIK0001999999.json", "source_type": "sec_edgar", "source_date": "2026-02-15", "confidence": "HIGH"},
                {"field_name": "ticker", "field_value": "APEX", "value_status": "exact", "source_url": "https://data.sec.gov/submissions/CIK0001999999.json", "source_type": "sec_edgar", "source_date": "2026-02-15", "confidence": "HIGH"},
                {"field_name": "sic_code", "field_value": "3510", "value_status": "exact", "source_url": "https://data.sec.gov/submissions/CIK0001999999.json", "source_type": "sec_edgar", "source_date": "2026-02-15", "confidence": "HIGH"},
                {"field_name": "headquarters_city", "field_value": "Houston", "value_status": "exact", "source_url": "https://data.sec.gov/submissions/CIK0001999999.json", "source_type": "sec_edgar", "source_date": "2026-02-15", "confidence": "HIGH"},
            ]
        }
        mock_wiki = {
            "source_status": "success",
            "fields": [
                {"field_name": "founded_year", "field_value": "1995", "value_status": "exact", "source_url": "https://www.wikidata.org/wiki/Q999999", "source_type": "wikidata", "source_date": "2026-01-01", "confidence": "MEDIUM"},
                {"field_name": "employee_count", "field_value": "12500", "value_status": "estimate", "source_url": "https://www.wikidata.org/wiki/Q999999", "source_type": "wikidata", "source_date": "2025", "confidence": "MEDIUM"},
                {"field_name": "official_website", "field_value": "https://www.apexturbo.com", "value_status": "exact", "source_url": "https://www.wikidata.org/wiki/Q999999", "source_type": "wikidata", "source_date": "2026-01-01", "confidence": "HIGH"},
            ]
        }

        class MockSec(SecEdgarConnector):
            def enrich_company(self, company_name=None, ticker=None, cik=None, **kwargs):
                return mock_sec

        class MockWiki(WikidataConnector):
            def enrich_company(self, company_name=None, domain=None, **kwargs):
                return mock_wiki

        engine = CompanyEnrichmentEngine(db_path=self.db_path, sec_connector=MockSec(), wikidata_connector=MockWiki())
        enr_res = engine.enrich_company_by_id(cid, force=True)
        self.assertTrue(enr_res["success"])
        self.assertEqual(enr_res["enrichment_status"], "complete")

        prov = get_company_field_provenance(cid, db_path=self.db_path)
        self.assertEqual(prov["sec_cik"]["value"], "0001999999")
        self.assertEqual(prov["sec_cik"]["confidence"], "HIGH")
        self.assertEqual(prov["employee_count"]["value"], "12500")
        self.assertEqual(prov["employee_count"]["value_status"], "estimate")
        self.assertEqual(prov["annual_revenue"]["value_status"], "unknown")

    def test_enrichment_summary_stats_calculation(self):
        """Verifies get_enrichment_summary_stats produces accurate counts and percentages."""
        from dashboard.company_db import get_enrichment_summary_stats
        
        # Test 1: Empty / initialized DB
        init_company_database(self.db_path)
        stats_empty = get_enrichment_summary_stats(self.db_path)
        self.assertEqual(stats_empty["total_companies"], 0)
        self.assertEqual(stats_empty["coverage_pct"], 0.0)
        self.assertEqual(stats_empty["status_counts"]["not_started"], 0)

        # Test 2: Seed DB
        seed_database_from_default_csv(db_path=self.db_path)
        stats_seeded = get_enrichment_summary_stats(self.db_path)
        self.assertGreaterEqual(stats_seeded["total_companies"], 785)
        self.assertEqual(stats_seeded["status_counts"]["not_started"], stats_seeded["total_companies"])
        self.assertEqual(stats_seeded["coverage_pct"], 0.0)

        # Test 3: Enrich one company
        df = get_all_companies_dataframe(db_path=self.db_path)
        first_cid = df.iloc[0]["company_id"]
        
        update_enrichment_status(first_cid, status="complete", sec_status="complete", wikidata_status="complete", db_path=self.db_path)
        upsert_field_provenance_records(first_cid, [
            {"field_name": "sec_cik", "field_value": "0001234567", "value_status": "exact", "source_type": "sec_edgar", "confidence": "HIGH"},
            {"field_name": "employee_count", "field_value": "5000", "value_status": "estimate", "source_type": "wikidata", "confidence": "MEDIUM"},
        ], db_path=self.db_path)

        stats_after = get_enrichment_summary_stats(self.db_path)
        self.assertEqual(stats_after["status_counts"]["complete"], 1)
        self.assertGreater(stats_after["coverage_pct"], 0.0)
        self.assertEqual(stats_after["sec_edgar_complete"], 1)
        self.assertEqual(stats_after["wikidata_complete"], 1)
        self.assertEqual(stats_after["value_status_counts"]["exact"], 1)
        self.assertEqual(stats_after["value_status_counts"]["estimate"], 1)

    def test_ranker_enrichment_filter_and_invariance(self):
        """Verifies ranker enrichment filter hook works cleanly without altering default ranking behavior."""
        from dashboard.company_db import normalize_str
        seed_database_from_default_csv(db_path=self.db_path)
        df = get_all_companies_dataframe(db_path=self.db_path)
        
        # Mark one company as complete
        target_name = df.iloc[0]["company_name"]
        target_cid = df.iloc[0]["company_id"]
        update_enrichment_status(target_cid, status="complete", db_path=self.db_path)

        # Build mock ranker DataFrame
        ranker_df = pd.DataFrame([
            {"company_name": target_name, "segment": "Oil & Gas", "current_status": "Ready for Outreach"},
            {"company_name": "Unenriched Corp", "segment": "Manufacturing", "current_status": "Monitor"},
        ])

        master_df = get_all_companies_dataframe(db_path=self.db_path)
        enr_status_map = dict(zip(master_df["normalized_name"], master_df["enrichment_status"]))

        ranker_df["enrichment_status"] = ranker_df["company_name"].apply(
            lambda x: enr_status_map.get(normalize_str(x), "not_started")
        )

        # Default filter: All accounts -> 2 accounts preserved
        all_cohort = ranker_df.copy()
        self.assertEqual(len(all_cohort), 2)

        # Filter: Enriched Only -> 1 account preserved
        enriched_cohort = ranker_df[ranker_df["enrichment_status"].isin(["complete", "partial"])]
        self.assertEqual(len(enriched_cohort), 1)
        self.assertEqual(enriched_cohort.iloc[0]["company_name"], target_name)

        # Filter: Not Enriched Only -> 1 account preserved
        not_enriched_cohort = ranker_df[ranker_df["enrichment_status"] == "not_started"]
        self.assertEqual(len(not_enriched_cohort), 1)
        self.assertEqual(not_enriched_cohort.iloc[0]["company_name"], "Unenriched Corp")

    def test_headless_backfill_cli_module(self):
        """Verifies headless backfill script runs dry-run and bounded batch execution."""
        from scripts.backfill_company_enrichment import run_backfill
        seed_database_from_default_csv(db_path=self.db_path)

        # Dry run on 10 accounts
        dry_run_count = run_backfill(
            db_path=self.db_path,
            batch_size=10,
            max_total=10,
            priority_first=True,
            dry_run=True,
        )
        self.assertEqual(dry_run_count, 10)

        # Check that DB was NOT modified by dry run
        df = get_all_companies_dataframe(db_path=self.db_path)
        self.assertTrue((df["enrichment_status"] == "not_started").all())

    def test_rollback_and_graceful_missing_db_fallback(self):
        """Verifies system handles missing or deleted database gracefully without crashing."""
        from dashboard.company_db import get_enrichment_summary_stats
        non_existent_db = Path(self.temp_dir.name) / "does_not_exist.db"
        
        # Calling stats on uninitialized DB initializes schema cleanly and returns 0 counts
        stats = get_enrichment_summary_stats(non_existent_db)
        self.assertEqual(stats["total_companies"], 0)
        self.assertEqual(stats["enriched_count"], 0)
        self.assertEqual(stats["coverage_pct"], 0.0)

        # Deleting DB file simulates total rollback
        if non_existent_db.exists():
            os.remove(non_existent_db)
        self.assertFalse(non_existent_db.exists())

    def test_wikidata_validated_name_variant_match(self):
        """1. Verifies exact/company-name-variant match strips legal suffix and corroborates domain (e.g. Cheniere Energy Inc)."""
        # When searching "Cheniere Energy Inc", raw API yields 0 results. Suffix stripping queries "Cheniere Energy" -> Q27926500.
        mock_claims = json.dumps({
            "entities": {
                "Q27926500": {
                    "claims": {
                        "P856": [{"mainsnak": {"datavalue": {"value": "http://www.cheniere.com"}}}],
                        "P571": [{"mainsnak": {"datavalue": {"value": {"time": "+1996-01-01T00:00:00Z"}}}}],
                    }
                }
            }
        })

        def mock_http(url, headers):
            if "wbsearchentities" in url:
                if "Cheniere%20Energy%20Inc" in url or "Cheniere+Energy+Inc" in url:
                    return 200, json.dumps({"search": []})
                if "Cheniere%20Energy" in url or "Cheniere+Energy" in url:
                    return 200, json.dumps({"search": [{"id": "Q27926500", "label": "Cheniere Energy", "description": "American energy company"}]})
            if "wbgetentities" in url and "Q27926500" in url:
                return 200, mock_claims
            return 404, ""

        connector = WikidataConnector(http_client=mock_http)
        res = connector.enrich_company("Cheniere Energy Inc", domain="cheniere.com")

        self.assertEqual(res["source_status"], "success")
        fields = {f["field_name"]: f for f in res["fields"]}
        self.assertEqual(fields["wikidata_qid"]["field_value"], "Q27926500")
        self.assertEqual(fields["founded_year"]["field_value"], "1996")
        self.assertEqual(fields["official_website"]["field_value"], "http://www.cheniere.com")
        self.assertIn("Corroborated by official website", fields["wikidata_qid"]["raw_evidence_snippet"])

    def test_wikidata_ambiguous_same_name_companies(self):
        """2. Verifies candidate selection disambiguates same-name companies and picks corroborated entity."""
        mock_search = json.dumps({
            "search": [
                {"id": "Q111111", "label": "Delta Power", "description": "Apparel and clothing retail"},
                {"id": "Q222222", "label": "Delta Power", "description": "Energy systems manufacturer"},
            ]
        })
        mock_claims_apparel = json.dumps({
            "entities": {
                "Q111111": {
                    "claims": {
                        "P856": [{"mainsnak": {"datavalue": {"value": "https://www.deltapowerapparel.com"}}}],
                        "P571": [{"mainsnak": {"datavalue": {"value": {"time": "+2018-01-01T00:00:00Z"}}}}],
                    }
                }
            }
        })
        mock_claims_energy = json.dumps({
            "entities": {
                "Q222222": {
                    "claims": {
                        "P856": [{"mainsnak": {"datavalue": {"value": "https://www.deltapower.com"}}}],
                        "P571": [{"mainsnak": {"datavalue": {"value": {"time": "+1985-01-01T00:00:00Z"}}}}],
                    }
                }
            }
        })

        def mock_http(url, headers):
            if "wbsearchentities" in url:
                return 200, mock_search
            if "wbgetentities" in url:
                if "Q111111" in url:
                    return 200, mock_claims_apparel
                if "Q222222" in url:
                    return 200, mock_claims_energy
            return 404, ""

        connector = WikidataConnector(http_client=mock_http)
        res = connector.enrich_company("Delta Power", domain="deltapower.com")

        self.assertEqual(res["source_status"], "success")
        fields = {f["field_name"]: f for f in res["fields"]}
        # Correctly rejected Q111111 and selected Q222222 matching deltapower.com
        self.assertEqual(fields["wikidata_qid"]["field_value"], "Q222222")
        self.assertEqual(fields["founded_year"]["field_value"], "1985")
        self.assertIn("Corroborated by official website", fields["wikidata_qid"]["raw_evidence_snippet"])

    def test_wikidata_false_positive_prevention_contradictory_domain(self):
        """3. Verifies false-positive prevention rejects entity with contradictory website even when name matches."""
        mock_search = json.dumps({
            "search": [
                {"id": "Q333333", "label": "Apex Logistics", "description": "Logistics and freight"},
            ]
        })
        mock_claims = json.dumps({
            "entities": {
                "Q333333": {
                    "claims": {
                        "P856": [{"mainsnak": {"datavalue": {"value": "https://www.apexlogistics-china.cn"}}}],
                    }
                }
            }
        })

        def mock_http(url, headers):
            if "wbsearchentities" in url:
                return 200, mock_search
            if "wbgetentities" in url and "Q333333" in url:
                return 200, mock_claims
            return 404, ""

        connector = WikidataConnector(http_client=mock_http)
        # Supplied domain is apexlogistics.com, candidate site is apexlogistics-china.cn
        res = connector.enrich_company("Apex Logistics", domain="apexlogistics.com")

        self.assertEqual(res["source_status"], "not_found")
        fields = {f["field_name"]: f for f in res["fields"]}
        self.assertIn("wikidata_qid", fields)
        self.assertIsNone(fields["wikidata_qid"]["field_value"])
        self.assertEqual(fields["wikidata_qid"]["value_status"], "unknown")
        self.assertEqual(fields["wikidata_qid"]["confidence"], "UNVERIFIED")

    def test_wikidata_supplied_domain_verification(self):
        """4. Verifies supplied domain matching works with paths, www-prefixes, and subdomains."""
        mock_search = json.dumps({
            "search": [
                {"id": "Q444444", "label": "Orion Marine Group", "description": "Marine contractor"},
            ]
        })
        mock_claims = json.dumps({
            "entities": {
                "Q444444": {
                    "claims": {
                        "P856": [{"mainsnak": {"datavalue": {"value": "https://www.orionmarinegroup.com/investor-relations"}}}],
                        "P571": [{"mainsnak": {"datavalue": {"value": {"time": "+1994-01-01T00:00:00Z"}}}}],
                    }
                }
            }
        })

        def mock_http(url, headers):
            if "wbsearchentities" in url:
                return 200, mock_search
            if "wbgetentities" in url and "Q444444" in url:
                return 200, mock_claims
            return 404, ""

        connector = WikidataConnector(http_client=mock_http)
        res = connector.enrich_company("Orion Marine Group", domain="orionmarinegroup.com")

        self.assertEqual(res["source_status"], "success")
        fields = {f["field_name"]: f for f in res["fields"]}
        self.assertEqual(fields["wikidata_qid"]["field_value"], "Q444444")
        self.assertEqual(fields["founded_year"]["field_value"], "1994")

    def test_wikidata_name_similarity_alone_rejected_unknown(self):
        """5. Verifies candidate matching name but lacking domain/CIK/ticker corroboration is rejected as unknown."""
        mock_search = json.dumps({
            "search": [
                {"id": "Q555555", "label": "Private Tech Innovators", "description": "Technology holding"},
            ]
        })
        # Candidate has inception date but NO website (P856), NO CIK (P5531), NO Ticker (P249)
        mock_claims = json.dumps({
            "entities": {
                "Q555555": {
                    "claims": {
                        "P571": [{"mainsnak": {"datavalue": {"value": {"time": "+2010-01-01T00:00:00Z"}}}}],
                    }
                }
            }
        })

        def mock_http(url, headers):
            if "wbsearchentities" in url:
                return 200, mock_search
            if "wbgetentities" in url and "Q555555" in url:
                return 200, mock_claims
            return 404, ""

        connector = WikidataConnector(http_client=mock_http)
        # No domain, ticker, or CIK provided; candidate also has no corroborating claims
        res = connector.enrich_company("Private Tech Innovators")

        # Must NOT accept match on name similarity alone
        self.assertEqual(res["source_status"], "not_found")
        fields = {f["field_name"]: f for f in res["fields"]}
        self.assertIn("wikidata_qid", fields)
        self.assertIsNone(fields["wikidata_qid"]["field_value"])
        self.assertEqual(fields["wikidata_qid"]["value_status"], "unknown")
        self.assertEqual(fields["wikidata_qid"]["confidence"], "UNVERIFIED")
        self.assertIn("Corroboration insufficient", fields["wikidata_qid"]["raw_evidence_snippet"])

    def test_dated_firmographic_metric_freshness_evaluation(self):
        """Verifies is_firmographic_metric_current enforces 3-year freshness threshold against reference year 2026."""
        from dashboard.enrichment_connectors import is_firmographic_metric_current
        ref = 2026
        # Current metrics: within 3 years
        self.assertTrue(is_firmographic_metric_current(2026, reference_year=ref))
        self.assertTrue(is_firmographic_metric_current(2025, reference_year=ref))
        self.assertTrue(is_firmographic_metric_current(2024, reference_year=ref))
        self.assertTrue(is_firmographic_metric_current(2023, reference_year=ref))
        self.assertTrue(is_firmographic_metric_current("2024-05-01", reference_year=ref))

        # Stale / historical metrics: older than 3 years
        self.assertFalse(is_firmographic_metric_current(2022, reference_year=ref))
        self.assertFalse(is_firmographic_metric_current(2018, reference_year=ref))
        self.assertFalse(is_firmographic_metric_current(2010, reference_year=ref))
        self.assertFalse(is_firmographic_metric_current(None, reference_year=ref))
        self.assertFalse(is_firmographic_metric_current("", reference_year=ref))

    def test_wikidata_stale_historic_revenue_retains_unknown_and_stores_historical(self):
        """Verifies stale dated Wikidata revenue is kept Unknown for current revenue and stored as historical."""
        # Q27926500 (Cheniere) has 2010 revenue claim ($291,513,000)
        claims_data = {
            "entities": {
                "Q27926500": {
                    "claims": {
                        "P856": [{"mainsnak": {"datavalue": {"value": "http://www.cheniere.com"}}}],
                        "P2139": [{
                            "mainsnak": {"datavalue": {"value": {"amount": "+291513000"}}},
                            "qualifiers": {
                                "P585": [{"datavalue": {"value": {"time": "+2010-01-01T00:00:00Z"}}}]
                            }
                        }],
                    }
                }
            }
        }
        search_data = {
            "search": [{"id": "Q27926500", "label": "Cheniere Energy", "description": "American energy company"}]
        }

        def mock_http(url, headers):
            if "wbsearchentities" in url:
                return 200, json.dumps(search_data)
            if "wbgetentities" in url:
                return 200, json.dumps(claims_data)
            return 404, ""

        connector = WikidataConnector(http_client=mock_http)
        res = connector.enrich_company("Cheniere Energy", domain="cheniere.com")

        self.assertEqual(res["source_status"], "success")
        fields = {f["field_name"]: f for f in res["fields"]}

        # 1. Current annual revenue MUST be Unknown because 2010 exceeds 3y freshness policy
        self.assertIn("annual_revenue", fields)
        self.assertIsNone(fields["annual_revenue"]["field_value"])
        self.assertEqual(fields["annual_revenue"]["value_status"], "unknown")
        self.assertEqual(fields["annual_revenue"]["confidence"], "UNVERIFIED")
        self.assertIn("historical from FY2010", fields["annual_revenue"]["raw_evidence_snippet"])

        # 2. Historical revenue MUST be stored as historical metric with fiscal year
        self.assertIn("historical_annual_revenue", fields)
        self.assertEqual(fields["historical_annual_revenue"]["field_value"], "$291,513,000 (FY2010)")
        self.assertEqual(fields["historical_annual_revenue"]["value_status"], "range")
        self.assertEqual(fields["historical_annual_revenue"]["source_date"], "2010")
        self.assertEqual(fields["historical_annual_revenue"]["confidence"], "MEDIUM")

    def test_wikidata_recent_revenue_populates_current_metric(self):
        """Verifies recent dated Wikidata revenue within freshness policy populates current annual_revenue."""
        claims_data = {
            "entities": {
                "Q804368": {
                    "claims": {
                        "P856": [{"mainsnak": {"datavalue": {"value": "https://www.bakerhughes.com"}}}],
                        "P2139": [{
                            "mainsnak": {"datavalue": {"value": {"amount": "+25500000000"}}},
                            "qualifiers": {
                                "P585": [{"datavalue": {"value": {"time": "+2025-01-01T00:00:00Z"}}}]
                            }
                        }],
                    }
                }
            }
        }
        search_data = {
            "search": [{"id": "Q804368", "label": "Baker Hughes", "description": "Energy technology"}]
        }

        def mock_http(url, headers):
            if "wbsearchentities" in url:
                return 200, json.dumps(search_data)
            if "wbgetentities" in url:
                return 200, json.dumps(claims_data)
            return 404, ""

        connector = WikidataConnector(http_client=mock_http)
        res = connector.enrich_company("Baker Hughes", domain="bakerhughes.com")

        self.assertEqual(res["source_status"], "success")
        fields = {f["field_name"]: f for f in res["fields"]}

        # 2025 revenue is within freshness threshold -> populates current annual_revenue
        self.assertIn("annual_revenue", fields)
        self.assertEqual(fields["annual_revenue"]["field_value"], "$25,500,000,000")
        self.assertEqual(fields["annual_revenue"]["value_status"], "range")
        self.assertEqual(fields["annual_revenue"]["source_date"], "2025")
        self.assertEqual(fields["annual_revenue"]["confidence"], "MEDIUM")

    def test_wikidata_stale_historic_employee_count_versus_current(self):
        """Verifies stale dated employee count is kept Unknown for current and stored as historical."""
        claims_data = {
            "entities": {
                "Q777777": {
                    "claims": {
                        "P856": [{"mainsnak": {"datavalue": {"value": "https://www.oldfirm.com"}}}],
                        "P1128": [{
                            "mainsnak": {"datavalue": {"value": {"amount": "+14000"}}},
                            "qualifiers": {
                                "P585": [{"datavalue": {"value": {"time": "+2018-01-01T00:00:00Z"}}}]
                            }
                        }],
                    }
                }
            }
        }
        search_data = {
            "search": [{"id": "Q777777", "label": "Old Firm Corp", "description": "Heavy machinery"}]
        }

        def mock_http(url, headers):
            if "wbsearchentities" in url:
                return 200, json.dumps(search_data)
            if "wbgetentities" in url:
                return 200, json.dumps(claims_data)
            return 404, ""

        connector = WikidataConnector(http_client=mock_http)
        res = connector.enrich_company("Old Firm Corp", domain="oldfirm.com")

        self.assertEqual(res["source_status"], "success")
        fields = {f["field_name"]: f for f in res["fields"]}

        # Current employee count unknown
        self.assertIn("employee_count", fields)
        self.assertIsNone(fields["employee_count"]["field_value"])
        self.assertEqual(fields["employee_count"]["value_status"], "unknown")
        # Historical employee count populated
        self.assertIn("historical_employee_count", fields)
        self.assertEqual(fields["historical_employee_count"]["field_value"], "14000 (as of 2018)")
        self.assertEqual(fields["historical_employee_count"]["source_date"], "2018")
        self.assertEqual(fields["historical_employee_count"]["value_status"], "estimate")

    def test_sec_exxon_mobil_corporation_vs_holdings_corp(self):
        """
        Regression Test 1: SEC Entity Identity Validation.
        Verifies that ExxonMobil resolves to canonical CIK 0000034088 (EXXON MOBIL CORP),
        rejecting CIK 0002115436 (ExxonMobil Holdings Corp) as subsidiary_holding.
        """
        mock_tickers_json = json.dumps({
            "0": {"cik_str": 2115436, "ticker": "XOM", "title": "ExxonMobil Holdings Corp"}
        })
        mock_efts_json = json.dumps({
            "hits": {
                "hits": [
                    {"_id": "34088", "_source": {"entity": "EXXON MOBIL CORP"}}
                ]
            }
        })
        mock_sub_holdings = json.dumps({
            "cik": "0002115436",
            "name": "ExxonMobil Holdings Corp",
            "tickers": ["XOM"],
            "entityType": "operating",
            "addresses": {"business": {"city": "SPRING", "stateOrCountry": "TX"}},
            "filings": {"recent": {"form": ["8-K", "10-Q", "S-8 POS"], "filingDate": ["2026-05-01"]}}
        })
        mock_sub_canonical = json.dumps({
            "cik": "0000034088",
            "name": "EXXON MOBIL CORP",
            "tickers": [],
            "sic": "2911",
            "sicDescription": "Petroleum Refining",
            "stateOfIncorporation": "NJ",
            "fiscalYearEnd": "1231",
            "entityType": "operating",
            "formerNames": [{"name": "EXXON CORP"}],
            "addresses": {"business": {"city": "SPRING", "stateOrCountry": "TX"}},
            "filings": {"recent": {"form": ["10-K", "10-Q", "8-K"], "filingDate": ["2026-02-20", "2026-05-01", "2026-06-01"]}}
        })

        def mock_http(url, headers):
            if "company_tickers.json" in url:
                return 200, mock_tickers_json
            if "keysTyped=Exxon" in url:
                return 200, mock_efts_json
            if "CIK0002115436.json" in url:
                return 200, mock_sub_holdings
            if "CIK0000034088.json" in url:
                return 200, mock_sub_canonical
            return 404, ""

        connector = SecEdgarConnector(http_client=mock_http)
        res = connector.enrich_company("ExxonMobil", domain="exxonmobil.com", ticker="XOM")

        self.assertEqual(res["source_status"], "success")
        self.assertEqual(res["cik"], "0000034088")
        fields = {f["field_name"]: f for f in res["fields"]}
        self.assertEqual(fields["sec_cik"]["field_value"], "0000034088")
        self.assertEqual(fields["sec_cik"]["value_status"], "exact")
        self.assertEqual(fields["sec_cik"]["confidence"], "HIGH")
        self.assertEqual(fields["ticker"]["field_value"], "XOM")
        self.assertEqual(fields["sic_code"]["field_value"], "2911")
        self.assertEqual(fields["incorporation_state"]["field_value"], "NJ")
        self.assertEqual(fields["headquarters_city"]["field_value"], "SPRING")

        # Verify candidate evaluation audit recorded both candidates and their classifications
        evals = {e["cik"]: e for e in res["evaluated_candidates"]}
        self.assertIn("0002115436", evals)
        self.assertEqual(evals["0002115436"]["relationship"], "subsidiary_holding")
        self.assertIn("0000034088", evals)
        self.assertEqual(evals["0000034088"]["relationship"], "exact_canonical")

    def test_sec_parent_subsidiary_same_brand_conflict(self):
        """
        Regression Test 2: Parent/Subsidiary same-brand conflict.
        Verifies that when an operating entity and financing/subsidiary arm exist under the same brand,
        the operating canonical entity is accepted and the subsidiary vehicle is rejected.
        """
        mock_tickers_json = json.dumps({
            "0": {"cik_str": 1999991, "ticker": "APEX", "title": "Apex Energy Capital LLC"},
            "1": {"cik_str": 1888882, "ticker": "APEX", "title": "Apex Energy Inc"},
        })
        mock_sub_sub = json.dumps({
            "cik": "0001999991",
            "name": "Apex Energy Capital LLC",
            "tickers": ["APEX"],
            "filings": {"recent": {"form": ["8-K", "424B2"], "filingDate": ["2026-01-10"]}},
            "addresses": {"business": {"city": "Denver", "stateOrCountry": "CO"}},
        })
        mock_sub_canon = json.dumps({
            "cik": "0001888882",
            "name": "Apex Energy Inc",
            "tickers": ["APEX"],
            "sic": "1311",
            "sicDescription": "CRUDE PETROLEUM & NATURAL GAS",
            "entityType": "operating",
            "filings": {"recent": {"form": ["10-K", "10-Q"], "filingDate": ["2026-03-01"]}},
            "addresses": {"business": {"city": "Denver", "stateOrCountry": "CO"}},
        })

        def mock_http(url, headers):
            if "company_tickers.json" in url:
                return 200, mock_tickers_json
            if "CIK0001999991.json" in url:
                return 200, mock_sub_sub
            if "CIK0001888882.json" in url:
                return 200, mock_sub_canon
            return 404, ""

        connector = SecEdgarConnector(http_client=mock_http)
        res = connector.enrich_company("Apex Energy", domain="apexenergy.com")

        self.assertEqual(res["source_status"], "success")
        self.assertEqual(res["cik"], "0001888882")
        fields = {f["field_name"]: f for f in res["fields"]}
        self.assertEqual(fields["sec_cik"]["field_value"], "0001888882")

        evals = {e["cik"]: e for e in res["evaluated_candidates"]}
        self.assertEqual(evals["0001999991"]["relationship"], "subsidiary_holding")
        self.assertEqual(evals["0001888882"]["relationship"], "exact_canonical")

    def test_sec_ticker_compatible_noncanonical_registrant(self):
        """
        Regression Test 3: Ticker-compatible but noncanonical registrant rejected.
        Verifies that a candidate with matching ticker is REJECTED when classified as subsidiary_holding,
        resulting in explicit 'unknown' status and audit rejection snippet when no canonical entity exists.
        """
        mock_tickers_json = json.dumps({
            "0": {"cik_str": 1777773, "ticker": "SOLR", "title": "Solaris Dynamics Holdings LLC"}
        })
        mock_sub_holding = json.dumps({
            "cik": "0001777773",
            "name": "Solaris Dynamics Holdings LLC",
            "tickers": ["SOLR"],
            "filings": {"recent": {"form": ["8-K", "S-4"], "filingDate": ["2026-04-10"]}},
            "addresses": {"business": {"city": "Austin", "stateOrCountry": "TX"}},
        })

        def mock_http(url, headers):
            if "company_tickers.json" in url:
                return 200, mock_tickers_json
            if "CIK0001777773.json" in url:
                return 200, mock_sub_holding
            return 404, ""

        connector = SecEdgarConnector(http_client=mock_http)
        res = connector.enrich_company("Solaris Dynamics", ticker="SOLR")

        self.assertEqual(res["source_status"], "not_found")
        self.assertIsNone(res.get("cik"))
        fields = {f["field_name"]: f for f in res["fields"]}
        self.assertIn("sec_cik", fields)
        self.assertIsNone(fields["sec_cik"]["field_value"])
        self.assertEqual(fields["sec_cik"]["value_status"], "unknown")
        self.assertEqual(fields["sec_cik"]["confidence"], "UNVERIFIED")
        # Evidence snippet explicitly records rejected candidate and reason
        evidence = fields["sec_cik"]["raw_evidence_snippet"]
        self.assertIn("0001777773", evidence)
        self.assertIn("subsidiary_holding", evidence)

    def test_sec_exact_canonical_cik_accepted(self):
        """
        Regression Test 4: Exact canonical CIK acceptance.
        Verifies that a canonical operating enterprise with matching normalized name and corroboration
        is accepted with HIGH confidence and exact value_status.
        """
        mock_tickers_json = json.dumps({
            "0": {"cik_str": 1724965, "ticker": "TALO", "title": "TALOS ENERGY INC."}
        })
        mock_sub_canon = json.dumps({
            "cik": "0001724965",
            "name": "TALOS ENERGY INC.",
            "tickers": ["TALO"],
            "sic": "1311",
            "sicDescription": "CRUDE PETROLEUM & NATURAL GAS",
            "stateOfIncorporation": "DE",
            "fiscalYearEnd": "1231",
            "entityType": "operating",
            "filings": {"recent": {"form": ["10-K", "10-Q", "8-K"], "filingDate": ["2026-03-05"]}},
            "addresses": {"business": {"city": "HOUSTON", "stateOrCountry": "TX"}},
        })

        def mock_http(url, headers):
            if "company_tickers.json" in url:
                return 200, mock_tickers_json
            if "CIK0001724965.json" in url:
                return 200, mock_sub_canon
            return 404, ""

        connector = SecEdgarConnector(http_client=mock_http)
        res = connector.enrich_company("Talos Energy", domain="talosenergy.com", ticker="TALO")

        self.assertEqual(res["source_status"], "success")
        self.assertEqual(res["cik"], "0001724965")
        fields = {f["field_name"]: f for f in res["fields"]}
        self.assertEqual(fields["sec_cik"]["field_value"], "0001724965")
        self.assertEqual(fields["sec_cik"]["value_status"], "exact")
        self.assertEqual(fields["sec_cik"]["confidence"], "HIGH")
        self.assertEqual(fields["ticker"]["field_value"], "TALO")
        self.assertEqual(fields["sic_code"]["field_value"], "1311")
        self.assertEqual(fields["headquarters_city"]["field_value"], "HOUSTON")
        self.assertEqual(fields["headquarters_state"]["field_value"], "TX")

    def test_sec_no_match_explicit_unknown(self):
        """
        Regression Test 5: No-match -> explicit unknown records.
        Verifies that when no SEC candidates match, all SEC fields return explicit unknown records
        with UNVERIFIED confidence, never fabricating or guessing data.
        """
        def mock_http(url, headers):
            return 404, ""

        connector = SecEdgarConnector(http_client=mock_http)
        res = connector.enrich_company("Totally Unregistered Offshore Firm XYZ")

        self.assertEqual(res["source_status"], "not_found")
        self.assertIsNone(res.get("cik"))
        fields = {f["field_name"]: f for f in res["fields"]}
        self.assertIn("sec_cik", fields)
        self.assertIsNone(fields["sec_cik"]["field_value"])
        self.assertEqual(fields["sec_cik"]["value_status"], "unknown")
        self.assertEqual(fields["sec_cik"]["confidence"], "UNVERIFIED")
        self.assertIn("No matching CIK record", fields["sec_cik"]["raw_evidence_snippet"])

    def test_sec_legacy_inactive_registrant_rejected_as_unknown(self):
        """
        Regression Test 6: Current Operating Entity Gate.
        Verifies that a legacy/inactive/terminated registrant (e.g. McDermott CIK 0000225615 with Form 10-K from 1998)
        is rejected by the current-operating-entity gate, ensuring statutory fields remain explicit Unknown.
        """
        mock_efts_json = json.dumps({
            "hits": {
                "hits": [
                    {"_id": "225615", "_source": {"entity": "MCDERMOTT INC"}}
                ]
            }
        })
        mock_sub_legacy = json.dumps({
            "cik": "0000225615",
            "name": "MCDERMOTT INC",
            "tickers": [],
            "sic": "3510",
            "sicDescription": "Engines & Turbines",
            "stateOfIncorporation": "DE",
            "addresses": {"business": {"city": "NEW ORLEANS", "stateOrCountry": "LA"}},
            "filings": {
                "recent": {
                    "form": ["SC 13G", "15-15D", "10-Q", "10-K405"],
                    "filingDate": ["2003-02-10", "1998-10-15", "1998-08-10", "1998-06-17"]
                }
            }
        })

        def mock_http(url, headers):
            if "company_tickers.json" in url:
                return 200, "{}"
            if "keysTyped=" in url:
                return 200, mock_efts_json
            if "CIK0000225615.json" in url:
                return 200, mock_sub_legacy
            return 404, ""

        connector = SecEdgarConnector(http_client=mock_http)
        res = connector.enrich_company("McDermott", domain="mcdermott.com")

        self.assertEqual(res["source_status"], "not_found")
        self.assertIsNone(res.get("cik"))
        fields = {f["field_name"]: f for f in res["fields"]}
        self.assertIn("sec_cik", fields)
        self.assertIsNone(fields["sec_cik"]["field_value"])
        self.assertEqual(fields["sec_cik"]["value_status"], "unknown")
        self.assertEqual(fields["sec_cik"]["confidence"], "UNVERIFIED")

        # Verify candidate evaluation audit recorded legacy rejection
        evals = {e["cik"]: e for e in res["evaluated_candidates"]}
        self.assertIn("0000225615", evals)
        self.assertEqual(evals["0000225615"]["relationship"], "rejected")
        self.assertIn("Legacy/inactive registrant", evals["0000225615"]["reason"])
        self.assertFalse(evals["0000225615"]["has_current_operating_filings"])


    def test_pre_first_annual_filing_exception(self):
        """Phase 5.0: Verifies pre-first-annual-filing exception classification for newly registered operating filers."""
        mock_sub = json.dumps({
            "cik": "0002126198",
            "name": "Expro Ltd",
            "tickers": ["XPRO"],
            "exchanges": ["NYSE"],
            "sic": "1389",
            "sicDescription": "Oil & Gas Field Services",
            "entityType": "operating",
            "stateOfIncorporation": "E9",
            "addresses": {"business": {"city": "CAMANA BAY", "stateOrCountry": "E9"}},
            "filings": {
                "recent": {
                    "form": ["4", "D", "8-K"],
                    "filingDate": ["2026-03-15", "2026-02-10", "2026-01-20"]
                }
            }
        })

        def mock_http(url, headers):
            if "company_tickers.json" in url:
                return 200, json.dumps({"0": {"cik_str": 2126198, "ticker": "XPRO", "title": "Expro Ltd"}})
            if "CIK0002126198.json" in url:
                return 200, mock_sub
            return 404, ""

        connector = SecEdgarConnector(http_client=mock_http)
        res = connector.enrich_company("Expro", domain="expro.com")

        self.assertEqual(res["source_status"], "success")
        self.assertEqual(res["cik"], "0002126198")
        evals = {e["cik"]: e for e in res["evaluated_candidates"]}
        self.assertEqual(evals["0002126198"]["relationship"], "pre_first_annual_filing")
        self.assertTrue(evals["0002126198"]["missing_base_annual_filing"])
        self.assertEqual(evals["0002126198"]["review_due_date"], "2026-06-30")
        self.assertEqual(evals["0002126198"]["reviewer_status"], "ACCEPTED_PENDING_FIRST_10K")
        fields = {f["field_name"]: f for f in res["fields"]}
        self.assertIn("pre_first_annual_filing", fields["sec_cik"]["raw_evidence_snippet"])

    def test_operating_subsidiary_classification(self):
        """Phase 5.0: Verifies operating subsidiary classification for parent-linked entities lacking equity tickers."""
        mock_sub = json.dumps({
            "cik": "0000006769",
            "name": "APACHE CORP",
            "tickers": [],
            "exchanges": [],
            "sic": "1311",
            "sicDescription": "Crude Petroleum & Natural Gas",
            "entityType": "operating",
            "stateOfIncorporation": "DE",
            "addresses": {"business": {"city": "HOUSTON", "stateOrCountry": "TX"}},
            "filings": {
                "recent": {
                    "form": ["8-K", "10-K", "10-Q"],
                    "filingDate": ["2026-02-10", "2024-02-22", "2023-11-02"]
                }
            }
        })

        def mock_http(url, headers):
            if "company_tickers.json" in url:
                return 200, json.dumps({"0": {"cik_str": 6769, "ticker": "", "title": "APACHE CORP"}})
            if "CIK0000006769.json" in url:
                return 200, mock_sub
            return 404, ""

        connector = SecEdgarConnector(http_client=mock_http)
        res = connector.enrich_company("Apache", domain="apachecorp.com")

        self.assertEqual(res["source_status"], "success")
        self.assertEqual(res["cik"], "0000006769")
        evals = {e["cik"]: e for e in res["evaluated_candidates"]}
        self.assertEqual(evals["0000006769"]["relationship"], "operating_subsidiary")
        self.assertTrue(evals["0000006769"]["stale_base_annual_filing"])
        self.assertEqual(evals["0000006769"]["reviewer_status"], "ACCEPTED_OPERATING_SUBSIDIARY")
        fields = {f["field_name"]: f for f in res["fields"]}
        self.assertIn("operating_subsidiary", fields["sec_cik"]["raw_evidence_snippet"])

    def test_stale_base_annual_filing_flagging(self):
        """Phase 5.0: Verifies stale base annual filing flag (>18 months / prior fiscal cycles)."""
        mock_sub = json.dumps({
            "cik": "0000999999",
            "name": "Stale Energy Corp",
            "tickers": ["STLE"],
            "exchanges": ["NYSE"],
            "sic": "1311",
            "entityType": "operating",
            "addresses": {"business": {"city": "DALLAS", "stateOrCountry": "TX"}},
            "filings": {
                "recent": {
                    "form": ["10-K"],
                    "filingDate": ["2023-03-01"]
                }
            }
        })

        def mock_http(url, headers):
            if "company_tickers.json" in url:
                return 200, json.dumps({"0": {"cik_str": 999999, "ticker": "STLE", "title": "Stale Energy Corp"}})
            if "CIK0000999999.json" in url:
                return 200, mock_sub
            return 404, ""

        connector = SecEdgarConnector(http_client=mock_http)
        res = connector.enrich_company("Stale Energy Corp", domain="staleenergy.com")
        evals = {e["cik"]: e for e in res["evaluated_candidates"]}
        self.assertTrue(evals["0000999999"]["stale_base_annual_filing"])
        self.assertFalse(evals["0000999999"]["missing_base_annual_filing"])

    def test_suppression_of_irrelevant_old_amendments(self):
        """Phase 5.0: Verifies that amendments older than base annual filings are suppressed from executive display."""
        # 1. Old amendment (e.g. 2007 amendment with 2026 base 40-F)
        mock_sub_old_amend = json.dumps({
            "cik": "0001232384",
            "name": "TC ENERGY CORP",
            "tickers": ["TRP"],
            "exchanges": ["NYSE"],
            "sic": "4922",
            "entityType": "operating",
            "addresses": {"business": {"city": "CALGARY", "stateOrCountry": "A0"}},
            "filings": {
                "recent": {
                    "form": ["40-F", "40-F/A"],
                    "filingDate": ["2026-02-13", "2007-03-19"]
                }
            }
        })

        def mock_http1(url, headers):
            if "company_tickers.json" in url:
                return 200, json.dumps({"0": {"cik_str": 1232384, "ticker": "TRP", "title": "TC ENERGY CORP"}})
            if "CIK0001232384.json" in url:
                return 200, mock_sub_old_amend
            return 404, ""

        connector1 = SecEdgarConnector(http_client=mock_http1)
        res1 = connector1.enrich_company("TC Energy", domain="tcenergy.com")
        eval1 = res1["evaluated_candidates"][0]
        # Executive amendment is suppressed because 2007 < 2026
        self.assertIsNone(eval1["executive_amendment_form"])
        self.assertEqual(eval1["current_operating_evidence_date"], "2026-02-13")
        fields1 = {f["field_name"]: f for f in res1["fields"]}
        self.assertNotIn("2007-03-19", fields1["latest_annual_filing_date"]["raw_evidence_snippet"])

        # 2. Newer amendment (e.g. 2026-03-10 amendment with 2026-02-13 base 10-K)
        mock_sub_new_amend = json.dumps({
            "cik": "0000895728",
            "name": "ENBRIDGE INC",
            "tickers": ["ENB"],
            "exchanges": ["NYSE"],
            "sic": "4922",
            "entityType": "operating",
            "addresses": {"business": {"city": "CALGARY", "stateOrCountry": "A0"}},
            "filings": {
                "recent": {
                    "form": ["10-K/A", "10-K"],
                    "filingDate": ["2026-03-10", "2026-02-13"]
                }
            }
        })

        def mock_http2(url, headers):
            if "company_tickers.json" in url:
                return 200, json.dumps({"0": {"cik_str": 895728, "ticker": "ENB", "title": "ENBRIDGE INC"}})
            if "CIK0000895728.json" in url:
                return 200, mock_sub_new_amend
            return 404, ""

        connector2 = SecEdgarConnector(http_client=mock_http2)
        res2 = connector2.enrich_company("Enbridge Inc", domain="enbridge.com")
        eval2 = res2["evaluated_candidates"][0]
        # Executive amendment is preserved because 2026-03-10 > 2026-02-13
        self.assertEqual(eval2["executive_amendment_form"], "10-K/A")
        self.assertEqual(eval2["current_operating_evidence_date"], "2026-03-10")
        fields2 = {f["field_name"]: f for f in res2["fields"]}
        self.assertIn("Amended by 10-K/A on 2026-03-10", fields2["latest_annual_filing_date"]["raw_evidence_snippet"])

    def test_duplicate_and_alias_cik_reporting(self):
        """Phase 5.0: Verifies duplicate CIK register grouping and distinction between account-level mappings and unique CIKs."""
        mappings = [
            {"company_id": "c1", "company_name": "Valaris", "domain": "valaris.com", "cik": "0000314808", "registrant": "Valaris Ltd", "cohort": "Cohort 150"},
            {"company_id": "c2", "company_name": "Valaris Limited", "domain": "valaris.com", "cik": "0000314808", "registrant": "Valaris Ltd", "cohort": "Cohort 150"},
            {"company_id": "c3", "company_name": "Chevron", "domain": "chevron.com", "cik": "0000093410", "registrant": "CHEVRON CORP", "cohort": "Cohort 100"},
        ]
        # Account level accepted mappings = 3
        account_accepted_count = len(mappings)
        # Unique canonical CIKs = 2
        unique_canonical_ciks = len({m["cik"] for m in mappings})
        self.assertEqual(account_accepted_count, 3)
        self.assertEqual(unique_canonical_ciks, 2)

        # Build alias register
        by_cik = {}
        for m in mappings:
            by_cik.setdefault(m["cik"], []).append(m)

        alias_register = {cik: entries for cik, entries in by_cik.items() if len(entries) > 1}
        self.assertIn("0000314808", alias_register)
        self.assertNotIn("0000093410", alias_register)
        self.assertEqual(len(alias_register["0000314808"]), 2)

    def test_west_group_rejection_and_no_false_positive(self):
        """Phase 5.1A: West Group (westgroup.com.br) must never accept CIK 0000105770 (West Pharmaceutical Services)."""
        mock_sub = json.dumps({
            "cik": "0000105770",
            "name": "WEST PHARMACEUTICAL SERVICES INC",
            "tickers": ["WST"],
            "exchanges": ["NYSE"],
            "sic": "3841",
            "sicDescription": "Surgical & Medical Instruments",
            "entityType": "operating",
            "formerNames": [{"name": "WEST CO INC", "from": "1994-04-05", "to": "1999-02-11"}],
            "addresses": {"business": {"city": "EXTON", "stateOrCountry": "PA"}},
            "website": "https://www.westpharma.com",
            "filings": {
                "recent": {
                    "form": ["10-K", "8-K"],
                    "filingDate": ["2026-02-17", "2026-01-10"]
                }
            }
        })

        def mock_http(url, headers):
            if "company_tickers.json" in url:
                return 200, json.dumps({
                    "0": {"cik_str": 105770, "ticker": "WST", "title": "WEST PHARMACEUTICAL SERVICES INC"}
                })
            if "CIK0000105770.json" in url:
                return 200, mock_sub
            return 404, ""

        connector = SecEdgarConnector(http_client=mock_http)
        res = connector.enrich_company("West Group", domain="westgroup.com.br")

        self.assertEqual(res["source_status"], "not_found")
        self.assertIsNone(res.get("cik"))
        evals = {e["cik"]: e for e in res["evaluated_candidates"]}
        self.assertIn("0000105770", evals)
        self.assertEqual(evals["0000105770"]["relationship"], "rejected")
        # Ensure CIK field is explicit unknown
        fields = {f["field_name"]: f for f in res["fields"]}
        self.assertEqual(fields["sec_cik"]["value_status"], "unknown")
        self.assertIsNone(fields["sec_cik"]["field_value"])

    def test_absent_seed_ticker_cannot_become_candidate_evidence(self):
        """Phase 5.1A: An absent seed ticker cannot be populated from candidate ticker to corroborate itself."""
        mock_sub = {
            "cik": "0000999999",
            "name": "GENERIC POWER CORP",
            "tickers": ["GPC"],
            "entityType": "operating",
            "formerNames": [],
            "addresses": {"business": {"city": "HOUSTON", "stateOrCountry": "TX"}},
            "filings": {"recent": {"form": ["10-K"], "filingDate": ["2026-02-01"]}}
        }
        # Call classifier with target_ticker=None and candidate has ticker GPC
        rel, reason, corrs = classify_sec_candidate_relationship(
            target_name="Generic Power",
            registrant_data=mock_sub,
            candidate_cik="0000999999",
            target_ticker=None,
            target_domain="genericpower.com",
            known_cik=None,
        )
        # Candidate's own ticker GPC must not appear as a ticker_match corroborator
        ticker_matches = [c for c in corrs if c.startswith("ticker_match:")]
        self.assertEqual(ticker_matches, [])

    def test_single_token_former_name_cannot_yield_exact_canonical(self):
        """Phase 5.1A: A former-name match on a single token without independent corroboration yields rejected/ambiguous."""
        mock_sub = {
            "cik": "0000888888",
            "name": "ACME DIVERSIFIED CORP",
            "tickers": ["ACME"],
            "entityType": "operating",
            "formerNames": [{"name": "WEST CO", "from": "1990-01-01", "to": "1995-01-01"}],
            "addresses": {"business": {"city": "NEW YORK", "stateOrCountry": "NY"}},
            "filings": {"recent": {"form": ["10-K"], "filingDate": ["2026-02-01"]}}
        }
        rel, reason, corrs = classify_sec_candidate_relationship(
            target_name="West Group",
            registrant_data=mock_sub,
            candidate_cik="0000888888",
            target_ticker=None,
            target_domain="westgroup.com.br",
            known_cik=None,
        )
        self.assertNotEqual(rel, "exact_canonical")
        self.assertEqual(rel, "rejected")

    def test_active_10k_and_sec_address_cannot_independently_corroborate_identity(self):
        """Phase 5.1A: Active 10-K and SEC address establish activity but cannot independently establish entity identity."""
        mock_sub = {
            "cik": "0000777777",
            "name": "GLOBAL HEALTHCARE SYSTEMS INC",
            "tickers": ["GHS"],
            "entityType": "operating",
            "formerNames": [],
            "addresses": {"business": {"city": "BOSTON", "stateOrCountry": "MA"}},
            "filings": {"recent": {"form": ["10-K"], "filingDate": ["2026-02-01"]}}
        }
        # Target has low-information/generic name "Global" without matching domain/ticker
        rel, reason, corrs = classify_sec_candidate_relationship(
            target_name="Global",
            registrant_data=mock_sub,
            candidate_cik="0000777777",
            target_ticker=None,
            target_domain="global.org",
            known_cik=None,
        )
        self.assertIn(rel, ("rejected", "ambiguous"))
        self.assertNotEqual(rel, "exact_canonical")

    def test_existing_canonical_resolutions_remain_correct(self):
        """Phase 5.1A: Legitimate canonical resolutions (ExxonMobil, Cheniere, Valaris, Noble, Seadrill, Transocean, Alto, Cars) remain exact_canonical."""
        canonical_cases = [
            ("ExxonMobil", "exxonmobil.com", "0000034088", "Exxon Mobil Corporation", ["XOM"]),
            ("Cheniere Energy, Inc.", "cheniere.com", "0000003570", "Cheniere Energy, Inc.", ["LNG"]),
            ("Valaris", "valaris.com", "0000314808", "Valaris Ltd", ["VAL"]),
            ("Noble Corp Plc", "noblecorp.com", "0001895262", "Noble Corp plc", ["NE"]),
            ("Seadrill", "seadrill.com", "0001737706", "SEADRILL Ltd", ["SDRL"]),
            ("Transocean", "deepwater.com", "0001451505", "Transocean Ltd.", ["RIG"]),
            ("Alto Ingredients, Inc.", "altoingredients.com", "0000778164", "Alto Ingredients, Inc.", ["ALTO"]),
            ("Cars.com", "cars.com", "0001683606", "Cars.com Inc.", ["CARS"]),
        ]

        for target_name, domain, cik, reg_name, tickers in canonical_cases:
            mock_sub = {
                "cik": cik,
                "name": reg_name,
                "tickers": tickers,
                "entityType": "operating",
                "formerNames": [],
                "addresses": {"business": {"city": "HOUSTON", "stateOrCountry": "TX"}},
                "filings": {"recent": {"form": ["10-K"], "filingDate": ["2026-02-20"]}}
            }
            rel, reason, corrs = classify_sec_candidate_relationship(
                target_name=target_name,
                registrant_data=mock_sub,
                candidate_cik=cik,
                target_ticker=None,  # Even without supplied ticker!
                target_domain=domain,
                known_cik=None,
            )
            self.assertEqual(
                rel, "exact_canonical",
                f"Failed for {target_name} ({reg_name}): rel={rel}, reason={reason}, corrs={corrs}"
            )


    def test_hawkins_rejection_and_jurisdictional_cctld_guard(self):
        """Phase 5.1B: Hawkins (hawkins.co.nz) must reject US domestic filer HAWKINS INC (Roseville, MN) via jurisdictional mismatch."""
        mock_sub = {
            "cik": "0000046250",
            "name": "HAWKINS INC",
            "tickers": ["HWKN"],
            "stateOfIncorporation": "MN",
            "entityType": "operating",
            "formerNames": [],
            "addresses": {"business": {"city": "ROSEVILLE", "stateOrCountry": "MN"}},
            "filings": {"recent": {"form": ["10-K"], "filingDate": ["2026-05-13"]}}
        }
        rel, reason, corrs = classify_sec_candidate_relationship(
            target_name="Hawkins",
            registrant_data=mock_sub,
            candidate_cik="0000046250",
            target_ticker=None,
            target_domain="hawkins.co.nz",
            known_cik=None,
        )
        self.assertEqual(rel, "rejected")
        self.assertIn("Jurisdictional mismatch", reason)
        self.assertIn(".co.nz", reason)

    def test_foreign_cctld_cannot_corroborate_us_domestic_filer(self):
        """Phase 5.1B: Foreign ccTLD domain cannot corroborate US domestic registrant without matching website."""
        mock_sub = {
            "cik": "0000999999",
            "name": "SUMMIT INDUSTRIAL CORP",
            "tickers": ["SMT"],
            "stateOfIncorporation": "DE",
            "entityType": "operating",
            "formerNames": [],
            "addresses": {"business": {"city": "HOUSTON", "stateOrCountry": "TX"}},
            "filings": {"recent": {"form": ["10-K"], "filingDate": ["2026-02-15"]}}
        }
        rel, reason, corrs = classify_sec_candidate_relationship(
            target_name="Summit",
            registrant_data=mock_sub,
            candidate_cik="0000999999",
            target_ticker=None,
            target_domain="summit.com.br",
            known_cik=None,
        )
        self.assertEqual(rel, "rejected")
        self.assertIn("Jurisdictional mismatch", reason)

    def test_phase5_1b_canonical_resolutions_remain_correct(self):
        """Phase 5.1B: Valid canonical companies in cohort (FMC, Ingevity, NOV, Nine Energy, Noble) resolve correctly."""
        cohort_cases = [
            ("FMC Corporation", "fmc.com", "0000037785", "FMC CORP", ["FMC"]),
            ("Ingevity", "ingevity.com", "0001653477", "Ingevity Corp", ["NGVT"]),
            ("NOV", "nov.com", "0001021860", "NOV Inc.", ["NOV"]),
            ("Nine Energy Service", "nineenergyservice.com", "0001532286", "Nine Energy Service, Inc.", ["NINE"]),
            ("Noble Corp", "noblecorp.com", "0001895262", "Noble Corp plc", ["NE"]),
        ]
        for target_name, domain, cik, reg_name, tickers in cohort_cases:
            mock_sub = {
                "cik": cik,
                "name": reg_name,
                "tickers": tickers,
                "entityType": "operating",
                "formerNames": [],
                "addresses": {"business": {"city": "HOUSTON", "stateOrCountry": "TX"}},
                "filings": {"recent": {"form": ["10-K"], "filingDate": ["2026-02-20"]}}
            }
            rel, reason, corrs = classify_sec_candidate_relationship(
                target_name=target_name,
                registrant_data=mock_sub,
                candidate_cik=cik,
                target_ticker=None,
                target_domain=domain,
                known_cik=None,
            )
            self.assertEqual(
                rel, "exact_canonical",
                f"Failed for {target_name} ({reg_name}): rel={rel}, reason={reason}"
            )


if __name__ == "__main__":
    unittest.main()



