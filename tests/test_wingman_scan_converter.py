"""
tests/test_wingman_scan_converter.py

Comprehensive test suite for scripts/convert_wingman_scans.py.
Verifies all mapping rules, validation gates, flattening rules, formula sanitization,
determinism, data leakage prevention, and integration with the Streamlit dashboard
validation (validate_custom_csv) and portfolio loading (load_wingman_portfolio) layers.
"""

import copy
import csv
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from typing import Any, Dict

import pandas as pd
import pytest

from dashboard.data_source import validate_custom_csv
from dashboard.wingman_portfolio import load_wingman_portfolio
from scripts.convert_wingman_scans import (
    CANONICAL_COLUMNS,
    ConversionError,
    ScanConverter,
    convert_wingman_scans,
    parse_scanned_at,
    sanitize_value_for_csv,
    standardize_segment,
    validate_trigger_date,
)

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "wingman_scans_sample.json"


@pytest.fixture
def sample_payload() -> Dict[str, Any]:
    """Loads the 5-company synthetic integration fixture."""
    with open(FIXTURE_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


# ==============================================================================
# 1. Structure and Payload Tests
# ==============================================================================


def test_exact_wrapped_api_response(sample_payload: Dict[str, Any], tmp_path: Path):
    """Verifies that the confirmed GET /api/scans wrapped structure converts successfully."""
    in_file = tmp_path / "wrapped.json"
    out_file = tmp_path / "wrapped.csv"
    in_file.write_text(json.dumps(sample_payload), encoding="utf-8")

    summary = convert_wingman_scans(in_file, out_file)
    assert summary["input_scan_records"] == 5
    assert summary["unique_companies"] == 5
    assert summary["output_trigger_rows"] == 4
    assert summary["zero_trigger_companies"] == 2
    assert summary["output_rows"] == 6
    assert summary["null_date_triggers"] == 1
    assert summary["missing_segment_fallbacks"] == 1
    assert summary["plaintext_citation_sources"] == 1
    assert summary["valid_url_sources"] == 3
    assert summary["total_contacts_held"] == 25
    assert out_file.exists()


def test_top_level_array_input(sample_payload: Dict[str, Any], tmp_path: Path):
    """Verifies that a top-level array of scan records converts successfully."""
    in_file = tmp_path / "array.json"
    out_file = tmp_path / "array.csv"
    in_file.write_text(json.dumps(sample_payload["scans"]), encoding="utf-8")

    summary = convert_wingman_scans(in_file, out_file)
    assert summary["input_scan_records"] == 5
    assert summary["output_rows"] == 6


@pytest.mark.parametrize(
    "bad_payload",
    [
        {"ok": False, "scans": []},
        {"scans": []},  # missing 'ok'
        {"ok": True},   # missing 'scans'
        {"ok": "true", "scans": []},  # string ok
        {"ok": True, "scans": "not a list"},
        "random string",
        12345,
        None,
    ],
)
def test_unsupported_top_level_structures(bad_payload: Any):
    """Verifies that non-standard top-level structures are rejected."""
    converter = ScanConverter()
    with pytest.raises(ConversionError):
        converter.parse_payload(bad_payload)


def test_malformed_json_cli(tmp_path: Path):
    """Verifies that malformed JSON input causes CLI failure with exit code 1."""
    bad_json_file = tmp_path / "malformed.json"
    bad_json_file.write_text("{ unclosed json: ", encoding="utf-8")
    out_file = tmp_path / "out.csv"

    res = subprocess.run(
        [sys.executable, "scripts/convert_wingman_scans.py", "--input", str(bad_json_file), "--output", str(out_file)],
        capture_output=True,
        text=True,
    )
    assert res.returncode == 1
    assert "Malformed JSON" in res.stderr


# ==============================================================================
# 2. Company & Flattening Rules
# ==============================================================================


def test_one_company_one_trigger():
    """Verifies that 1 company with 1 trigger emits exactly 1 row."""
    scan = [
        {
            "company": "Alpha Corp",
            "segment": "Oil & Gas",
            "tier": 2,
            "triggers": [
                {
                    "type": "turnaround",
                    "value": "TAR scheduled",
                    "source": "https://example.com/tar",
                    "date": "2026-08-01",
                }
            ],
            "scanned_at": "2026-09-01T00:00:00Z",
        }
    ]
    converter = ScanConverter()
    rows = converter.process_records(scan)
    assert len(rows) == 1
    r = rows[0]
    assert r["company"] == "Alpha Corp"
    assert r["segment"] == "Oil & Gas"
    assert r["source_tier"] == "2"
    assert r["trigger_type"] == "turnaround"
    assert r["trigger_date"] == "2026-08-01"
    assert r["trigger_summary"] == "TAR scheduled"
    assert r["trigger_source_url"] == "https://example.com/tar"
    assert r["scanned_at"] == "2026-09-01"


def test_one_company_multiple_triggers():
    """Verifies that 1 company with multiple triggers emits 1 row per trigger preserving order."""
    scan = [
        {
            "company": "Beta Corp",
            "segment": "Chemicals",
            "tier": 1,
            "triggers": [
                {"type": "project_fid_commissioning", "value": "FID", "source": "", "date": "2026-08-01"},
                {"type": "hiring_burst", "value": "Hiring", "source": "", "date": "2026-08-05"},
                {"type": "new_leader", "value": "New VP", "source": "", "date": "2026-08-10"},
            ],
            "scanned_at": "2026-09-01T00:00:00Z",
        }
    ]
    converter = ScanConverter()
    rows = converter.process_records(scan)
    assert len(rows) == 3
    assert [r["trigger_type"] for r in rows] == [
        "project_fid_commissioning",
        "hiring_burst",
        "new_leader",
    ]
    assert [r["trigger_date"] for r in rows] == ["2026-08-01", "2026-08-05", "2026-08-10"]


def test_zero_trigger_company_preservation():
    """Verifies that a zero-trigger company emits exactly 1 row with empty trigger fields."""
    scan = [
        {
            "company": "Gamma Corp",
            "segment": "Oil & Gas",
            "tier": 3,
            "triggers": [],
            "scanned_at": "2026-09-01T00:00:00Z",
        }
    ]
    converter = ScanConverter()
    rows = converter.process_records(scan)
    assert len(rows) == 1
    r = rows[0]
    assert r["company"] == "Gamma Corp"
    assert r["source_tier"] == "3"
    assert r["trigger_type"] == ""
    assert r["trigger_date"] == ""
    assert r["trigger_summary"] == ""
    assert r["trigger_source_url"] == ""


def test_null_trigger_array():
    """Verifies that null triggers array is normalized to [] with a warning, emitting 1 row."""
    scan = [
        {
            "company": "Delta Corp",
            "segment": "Oil & Gas",
            "tier": 3,
            "triggers": None,
            "scanned_at": "2026-09-01T00:00:00Z",
        }
    ]
    converter = ScanConverter()
    rows = converter.process_records(scan)
    assert len(rows) == 1
    assert rows[0]["trigger_type"] == ""
    assert converter.null_trigger_arrays == 1
    assert any("normalized to []" in w for w in converter.warnings)


def test_null_trigger_date():
    """Verifies that null or blank trigger date converts with a warning as blank string."""
    scan = [
        {
            "company": "Epsilon Corp",
            "segment": "Oil & Gas",
            "tier": 2,
            "triggers": [
                {"type": "turnaround", "value": "TAR", "source": "", "date": None},
                {"type": "hiring_burst", "value": "Jobs", "source": "", "date": ""},
            ],
            "scanned_at": "2026-09-01T00:00:00Z",
        }
    ]
    converter = ScanConverter()
    rows = converter.process_records(scan)
    assert len(rows) == 2
    assert rows[0]["trigger_date"] == ""
    assert rows[1]["trigger_date"] == ""
    assert converter.null_date_triggers == 2


# ==============================================================================
# 3. Validation & Rejection Gates (Blocking Errors)
# ==============================================================================


@pytest.mark.parametrize(
    "bad_date",
    ["2026-02-31", "2026/08/15", "yesterday", "2026-13-01", "2026-Q3", "2026-08"],
)
def test_invalid_trigger_date(bad_date: str):
    """Verifies that impossible or malformed nonblank trigger dates are rejected."""
    scan = [
        {
            "company": "Bad Date Corp",
            "segment": "Oil & Gas",
            "tier": 2,
            "triggers": [{"type": "turnaround", "value": "TAR", "source": "", "date": bad_date}],
            "scanned_at": "2026-09-01T00:00:00Z",
        }
    ]
    converter = ScanConverter()
    with pytest.raises(ConversionError, match="trigger date"):
        converter.process_records(scan)


@pytest.mark.parametrize("bad_timestamp", ["invalid-timestamp", "2026/09/15", "not-a-date"])
def test_invalid_scanned_at(bad_timestamp: str):
    """Verifies that malformed nonblank scanned_at timestamps are rejected."""
    scan = [
        {
            "company": "Bad Scan Corp",
            "segment": "Oil & Gas",
            "tier": 3,
            "triggers": [],
            "scanned_at": bad_timestamp,
        }
    ]
    converter = ScanConverter()
    with pytest.raises(ConversionError, match="scanned_at"):
        converter.process_records(scan)


@pytest.mark.parametrize("bad_type", ["unrecognized_catalyst", "marketing_burst", "", None])
def test_unknown_trigger_type(bad_type: Any):
    """Verifies that non-canonical trigger types are rejected."""
    scan = [
        {
            "company": "Bad Type Corp",
            "segment": "Oil & Gas",
            "tier": 2,
            "triggers": [{"type": bad_type, "value": "desc", "source": "", "date": "2026-08-01"}],
            "scanned_at": "2026-09-01T00:00:00Z",
        }
    ]
    converter = ScanConverter()
    with pytest.raises(ConversionError, match="trigger type"):
        converter.process_records(scan)


@pytest.mark.parametrize("bad_company", ["", "   ", None])
def test_missing_company(bad_company: Any):
    """Verifies that missing or blank company names are rejected."""
    scan = [
        {
            "company": bad_company,
            "segment": "Oil & Gas",
            "tier": 3,
            "triggers": [],
            "scanned_at": "2026-09-01T00:00:00Z",
        }
    ]
    converter = ScanConverter()
    with pytest.raises(ConversionError, match="missing or blank 'company'"):
        converter.process_records(scan)


@pytest.mark.parametrize("bad_tier", [0, 4, 99, -1, "Tier 1", "invalid", None])
def test_invalid_tier(bad_tier: Any):
    """Verifies that invalid source tiers are rejected."""
    scan = [
        {
            "company": "Bad Tier Corp",
            "segment": "Oil & Gas",
            "tier": bad_tier,
            "triggers": [],
            "scanned_at": "2026-09-01T00:00:00Z",
        }
    ]
    converter = ScanConverter()
    with pytest.raises(ConversionError, match="source tier"):
        converter.process_records(scan)


def test_duplicate_company_different_casing():
    """Verifies that duplicate companies with different casing are rejected."""
    scan = [
        {"company": "Apex Energy", "segment": "Oil & Gas", "tier": 3, "triggers": [], "scanned_at": ""},
        {"company": "apex energy", "segment": "Oil & Gas", "tier": 3, "triggers": [], "scanned_at": ""},
    ]
    converter = ScanConverter()
    with pytest.raises(ConversionError, match="Duplicate company detected"):
        converter.process_records(scan)


# ==============================================================================
# 4. Fallbacks, Sources, and Domain Tests
# ==============================================================================


@pytest.mark.parametrize("empty_segment", [None, "", "   "])
def test_missing_segment_fallback(empty_segment: Any):
    """Verifies that missing or blank segment falls back to 'Diversified Industrial / Unspecified'."""
    scan = [
        {
            "company": "Fallback Corp",
            "segment": empty_segment,
            "tier": 3,
            "triggers": [],
            "scanned_at": "",
        }
    ]
    converter = ScanConverter()
    rows = converter.process_records(scan)
    assert rows[0]["segment"] == "Diversified Industrial / Unspecified"
    assert converter.missing_segment_fallbacks == 1


def test_missing_and_present_domain():
    """Verifies domain handling: blank when omitted, normalized when present."""
    scan = [
        {
            "company": "No Domain Corp",
            "segment": "Oil & Gas",
            "tier": 3,
            "triggers": [],
            "scanned_at": "",
        },
        {
            "company": "Domain Corp",
            "domain": "https://www.example.com/careers",
            "segment": "Oil & Gas",
            "tier": 3,
            "triggers": [],
            "scanned_at": "",
        },
    ]
    converter = ScanConverter()
    rows = converter.process_records(scan)
    # Sorted case-insensitively: Domain Corp, No Domain Corp
    domain_map = {r["company"]: r["domain"] for r in rows}
    assert domain_map["No Domain Corp"] == ""
    assert domain_map["Domain Corp"] == "example.com"
    assert converter.missing_domains == 1


def test_url_and_plaintext_citation_sources():
    """Verifies distinguishing URL sources vs plain-text citations."""
    scan = [
        {
            "company": "Media Corp",
            "segment": "Oil & Gas",
            "tier": 1,
            "triggers": [
                {
                    "type": "turnaround",
                    "value": "TAR",
                    "source": "https://example.com/press",
                    "date": "2026-08-01",
                },
                {
                    "type": "hiring_burst",
                    "value": "Hiring",
                    "source": "Industrial Info Resources Bulletin",
                    "date": "2026-08-02",
                },
            ],
            "scanned_at": "",
        }
    ]
    converter = ScanConverter()
    rows = converter.process_records(scan)
    assert converter.valid_url_sources == 1
    assert converter.plaintext_citation_sources == 1
    assert rows[0]["trigger_source_url"] == "https://example.com/press"
    assert rows[1]["trigger_source_url"] == "Industrial Info Resources Bulletin"


# ==============================================================================
# 5. Security & Privacy Safeguards
# ==============================================================================


@pytest.mark.parametrize("prefix", ["=", "+", "-", "@", "\t", "\r", "\n"])
def test_formula_injection_attempts_in_every_text_field(prefix: str):
    """Verifies CSV formula injection protection (CWE-1236 / OWASP) across all exported text cells."""
    malicious_text = f"{prefix}cmd|' /C calc'!A0"
    scan = [
        {
            "company": malicious_text,
            "segment": malicious_text,
            "domain": malicious_text,
            "tier": 2,
            "triggers": [
                {
                    "type": "turnaround",
                    "value": malicious_text,
                    "source": malicious_text,
                    "date": "2026-08-01",
                }
            ],
            "scanned_at": "",
        }
    ]
    converter = ScanConverter()
    rows = converter.process_records(scan)
    r = rows[0]
    for field in ["company", "segment", "domain", "trigger_summary", "trigger_source_url"]:
        val = r[field]
        assert val.startswith("'"), f"Field {field} value {val!r} must be escaped with a single quote prefix."


def test_no_notes_id_or_contacts_held_leakage(sample_payload: Dict[str, Any], tmp_path: Path):
    """Verifies that internal id, notes, and contacts_held are never written to the CSV."""
    out_file = tmp_path / "out.csv"
    in_file = tmp_path / "in.json"
    in_file.write_text(json.dumps(sample_payload), encoding="utf-8")

    convert_wingman_scans(in_file, out_file)
    content = out_file.read_text(encoding="utf-8")

    # Header verification
    reader = csv.reader(content.splitlines())
    header = next(reader)
    assert header == CANONICAL_COLUMNS
    assert "id" not in header
    assert "notes" not in header
    assert "contacts_held" not in header

    # Value verification: notes text from fixture must not appear anywhere in file
    assert "Verified facility operator with deepwater LNG terminal assets" not in content
    assert "Third-party engineering consultancy" not in content


def test_no_contact_tier_mapping(sample_payload: Dict[str, Any], tmp_path: Path):
    """Verifies that scan tier maps strictly to source_tier, not contact tier."""
    out_file = tmp_path / "out.csv"
    in_file = tmp_path / "in.json"
    in_file.write_text(json.dumps(sample_payload), encoding="utf-8")

    convert_wingman_scans(in_file, out_file)
    df = pd.read_csv(out_file)
    assert "source_tier" in df.columns
    assert "contact_tier" not in df.columns
    assert set(df["source_tier"].unique()).issubset({1, 2, 3})


# ==============================================================================
# 6. Determinism & Stability
# ==============================================================================


def test_stable_ordering_and_byte_identical_output(sample_payload: Dict[str, Any], tmp_path: Path):
    """Verifies that identical input produces byte-identical output with stable sorting."""
    out1 = tmp_path / "out1.csv"
    out2 = tmp_path / "out2.csv"
    in_file = tmp_path / "in.json"

    # Shuffle the input order in in_file to ensure sorting is deterministic
    shuffled_payload = copy.deepcopy(sample_payload)
    shuffled_payload["scans"].reverse()
    in_file.write_text(json.dumps(shuffled_payload), encoding="utf-8")

    convert_wingman_scans(in_file, out1)
    convert_wingman_scans(in_file, out2)

    bytes1 = out1.read_bytes()
    bytes2 = out2.read_bytes()
    assert hashlib.sha256(bytes1).hexdigest() == hashlib.sha256(bytes2).hexdigest()

    # Verify company order is alphabetical
    df = pd.read_csv(out1)
    companies = list(df["company"].unique())
    assert companies == sorted(companies, key=lambda c: c.lower())


# ==============================================================================
# 7. Integration with Streamlit Dashboard Validation & Portfolio Engine
# ==============================================================================


def test_generated_csv_passes_validate_custom_csv(tmp_path: Path):
    """Verifies that the generated CSV passes the dashboard's schema and safety validator."""
    out_file = tmp_path / "converted.csv"
    convert_wingman_scans(FIXTURE_PATH, out_file)

    raw_bytes = out_file.read_bytes()
    val_res = validate_custom_csv(raw_bytes, "converted.csv")

    assert val_res.is_valid is True
    assert val_res.blocking_errors == []
    assert val_res.company_count == 5
    assert val_res.row_count == 6
    assert val_res.companies_without_triggers_count == 2
    assert val_res.recognized_trigger_rows_count == 4
    # Latest valid scanned_at across the 5 companies is 2026-09-15
    assert str(val_res.suggested_as_of_date) == "2026-09-15"


def test_generated_csv_loads_through_load_wingman_portfolio(tmp_path: Path):
    """Verifies that the generated CSV loads cleanly through load_wingman_portfolio."""
    out_file = tmp_path / "converted.csv"
    convert_wingman_scans(FIXTURE_PATH, out_file)

    raw_bytes = out_file.read_bytes()
    val_res = validate_custom_csv(raw_bytes, "converted.csv")

    portfolio = load_wingman_portfolio(input_df=val_res.clean_df, is_custom=True)
    assert portfolio is not None
    companies_df = portfolio["companies_df"]
    assert len(companies_df) == 5


def test_null_date_trigger_remains_undated_not_active(tmp_path: Path):
    """
    Verifies that a trigger with a null date (Crestview Engineering Partners)
    remains undated and is not counted as active in the portfolio evaluation.
    """
    out_file = tmp_path / "converted.csv"
    convert_wingman_scans(FIXTURE_PATH, out_file)

    val_res = validate_custom_csv(out_file.read_bytes(), "converted.csv")
    portfolio = load_wingman_portfolio(input_df=val_res.clean_df, is_custom=True)
    companies_df = portfolio["companies_df"]

    crestview = companies_df[companies_df["company_name"] == "Crestview Engineering Partners"].iloc[0]
    assert crestview["distinct_category_count"] == 0
    assert crestview["active_event_count"] == 0
    assert crestview["queue_category"] == "Monitor"


def test_computed_tier_recalculated_not_copied_from_source_tier(tmp_path: Path):
    """
    Verifies that computed_tier is dynamically recalculated based on active catalysts,
    and legitimately differs from the static source_tier:
    - Crestview: source_tier is Tier 2, but computed_tier is Nurture / Tier 3 (due to null date).
    - Apex: source_tier is Tier 1, computed_tier is Tier 1 (2 active distinct categories).
    - Beacon: source_tier is Tier 2, computed_tier is Tier 2 (1 active category).
    """
    out_file = tmp_path / "converted.csv"
    convert_wingman_scans(FIXTURE_PATH, out_file)

    val_res = validate_custom_csv(out_file.read_bytes(), "converted.csv")
    portfolio = load_wingman_portfolio(input_df=val_res.clean_df, is_custom=True)
    companies_df = portfolio["companies_df"]

    by_name = {row["company_name"]: row for _, row in companies_df.iterrows()}

    # Crestview has source_tier=Tier 2, but computed_tier=Nurture
    assert by_name["Crestview Engineering Partners"]["source_tier"] == "Tier 2"
    assert by_name["Crestview Engineering Partners"]["computed_tier"] == "Nurture"

    # Apex has source_tier=Tier 1 and computed_tier=Tier 1
    assert by_name["Apex Energy Systems"]["source_tier"] == "Tier 1"
    assert by_name["Apex Energy Systems"]["computed_tier"] == "Tier 1"

    # Beacon has source_tier=Tier 2 and computed_tier=Tier 2
    assert by_name["Beacon Chemical Technologies"]["source_tier"] == "Tier 2"
    assert by_name["Beacon Chemical Technologies"]["computed_tier"] == "Tier 2"


def test_cli_execution_summary_format(tmp_path: Path):
    """Verifies CLI execution, exit code 0, and exact formatted summary console output."""
    out_file = tmp_path / "cli_out.csv"
    res = subprocess.run(
        [sys.executable, "scripts/convert_wingman_scans.py", "--input", str(FIXTURE_PATH), "--output", str(out_file)],
        capture_output=True,
        text=True,
    )
    assert res.returncode == 0
    stdout = res.stdout
    assert "Wingman Scan Converter Summary" in stdout
    assert "Input scan records:             5" in stdout
    assert "Unique companies:               5" in stdout
    assert "Output trigger rows:            4" in stdout
    assert "Zero-trigger companies:         2" in stdout
    assert "Null-date triggers:             1" in stdout
    assert "Missing-segment fallbacks:      1" in stdout
    assert "Plain-text citation sources:    1" in stdout
    assert "Valid URL sources:              3" in stdout
    assert "Total contacts_held:            25" in stdout
    assert "Output rows:                    6" in stdout
    assert "Conversion completed successfully." in stdout
