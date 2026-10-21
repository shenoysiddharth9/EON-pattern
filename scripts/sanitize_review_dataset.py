"""
Deterministic Sanitization Script for Wingman External Review Dataset.
Transforms local_data/wingman-trigger-export-2026-09-17.csv into a client-safe,
executive-ready dataset for the Streamlit Community Cloud external review build:
- Preserves raw input as immutable
- Standardizes segment naming across all records
- Preserves all 1,180 rows and 785 unique companies with 100% fidelity
- Preserves nonstandard Sinopec date strings ('2026-Q3 (target, article 2025-05-23)', '2026-09 (listing ~17 days old as of Sep 2026 search)')
- Completely drops internal prototype 'pattern_report_url'
- Completely strips raw 'notes' column, replacing it with standardized business reason codes
"""

from pathlib import Path
import re
from typing import Any, Dict, Tuple
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
INPUT_PATH = PROJECT_ROOT / "local_data" / "wingman-trigger-export-2026-09-17.csv"
OUTPUT_DIR = PROJECT_ROOT / "data"
OUTPUT_PATH = OUTPUT_DIR / "wingman-trigger-export-2026-09-17-sanitized.csv"

def standardize_segment(val: Any) -> str:
    """Standardizes industry segment labels using clean title casing."""
    if not val or pd.isna(val):
        return "Unknown"
    s = str(val).strip()
    s_lower = s.lower()
    
    if s_lower in ["oil and gas", "oil & gas", "oil & energy"]:
        return "Oil & Gas"
    if s_lower in ["chemicals & petrochemicals", "chemical manufacturing"]:
        return "Chemicals & Petrochemicals"
    if s_lower in ["var", "imported"]:
        return "Diversified Industrial / Unspecified"
    if s_lower == "information technology & services":
        return "Information Technology"
    if s_lower in ["higher education", "education administration programs"]:
        return "Education & Training"
    if s_lower == "paper & forest products":
        return "Forest Products"
    if s_lower == "machinery":
        return "Machinery & Equipment"
    if s_lower == "maritime":
        return "Maritime & Shipping"
    if s_lower == "financial services":
        return "Financial Services"
    if s_lower == "government administration":
        return "Government Administration"
    if s_lower == "luxury goods & jewelry":
        return "Consumer / Specialty Goods"
    if s_lower == "marketing & advertising":
        return "Marketing & Communications"
    if s_lower == "retail":
        return "Retail Distribution"
    if s_lower == "construction":
        return "Construction & Civil Works"
        
    return s.title()

REVIEW_QUESTIONS = {
    "ACADEMIC_INCUBATOR": "Does this organization operate pilot process plants or industrial spinouts with physical operating procedures?",
    "TRAINING_PROVIDER": "Does this training organization own/operate industrial process facilities or license external operational procedure technology for workforce simulation?",
    "NON_OPERATOR_DISTRIBUTOR": "Does this distributor manage bulk terminal storage, gas processing plants, or physical fluid transfer operations requiring formal procedure qualification?",
    "SERVICE_CONTRACTOR": "Does this contractor operate client-owned process plant assets, offshore platforms, or drilling vessels requiring frontline procedure execution?",
    "CONSULTING_FIRM": "Does this advisory firm deliver owner's engineering or hands-on operating procedure implementation for industrial plant sites?",
    "HOLDING_COMPANY": "Which operating corporate entity or plant subsidiary holds direct ownership and operational control of the physical assets?",
    "GENERAL_NON_OPERATOR": "Does this company have direct operational control over high-hazard industrial process equipment?",
    "STANDARD_UNASSESSED": "Standard operator profile unassessed. Confirm operational plant assets during SDR discovery.",
}

def extract_review_reason(notes: Any) -> Tuple[bool, str, str, str, str]:
    """
    Deterministic rule-based extraction of business profile review codes.
    Returns: (is_review_required, review_reason_code, review_reason_label, matched_keyword, recommended_question)
    """
    if not notes or pd.isna(notes):
        return False, "STANDARD_UNASSESSED", "Operational profile unassessed (standard operator candidate)", "", REVIEW_QUESTIONS["STANDARD_UNASSESSED"]
        
    n_lower = str(notes).lower()
    
    for kw in ["tech office", "technology transfer", "incubator", "university"]:
        if kw in n_lower:
            return True, "ACADEMIC_INCUBATOR", "Academic incubator / technology transfer office", kw, REVIEW_QUESTIONS["ACADEMIC_INCUBATOR"]
            
    for kw in ["training center", "training provider", "training institute", "training academy"]:
        if kw in n_lower:
            return True, "TRAINING_PROVIDER", "Third-party safety training center provider", kw, REVIEW_QUESTIONS["TRAINING_PROVIDER"]
            
    for kw in ["not an o&g refiner", "specialty resin", "distributor", "broker"]:
        if kw in n_lower:
            return True, "NON_OPERATOR_DISTRIBUTOR", "Specialty product distributor / non-refining entity", kw, REVIEW_QUESTIONS["NON_OPERATOR_DISTRIBUTOR"]
            
    for kw in ["service contractor", "civil works", "epc contractor"]:
        if kw in n_lower:
            return True, "SERVICE_CONTRACTOR", "Service contractor / non-plant asset operator", kw, REVIEW_QUESTIONS["SERVICE_CONTRACTOR"]
            
    for kw in ["consulting firm", "consultancy"]:
        if kw in n_lower:
            return True, "CONSULTING_FIRM", "Consultancy / professional advisory service", kw, REVIEW_QUESTIONS["CONSULTING_FIRM"]
            
    for kw in ["holding company only"]:
        if kw in n_lower:
            return True, "HOLDING_COMPANY", "Holding company structure without direct operating assets", kw, REVIEW_QUESTIONS["HOLDING_COMPANY"]
            
    for kw in ["non-operator", "not an operator", "out of scope"]:
        if kw in n_lower:
            return True, "GENERAL_NON_OPERATOR", "Service provider / non-operating facility", kw, REVIEW_QUESTIONS["GENERAL_NON_OPERATOR"]
            
    return False, "STANDARD_UNASSESSED", "Operational profile unassessed (standard operator candidate)", "", REVIEW_QUESTIONS["STANDARD_UNASSESSED"]

def main():
    print(f"Reading raw CSV from: {INPUT_PATH}")
    assert INPUT_PATH.exists(), f"Input CSV does not exist at {INPUT_PATH}"
    
    df = pd.read_csv(INPUT_PATH, encoding="utf-8-sig")
    initial_rows = len(df)
    initial_companies = df["company"].nunique()
    
    print(f"Raw received: {initial_rows} rows, {initial_companies} unique companies.")
    
    # 1. Standardize segment
    df["segment"] = df["segment"].apply(standardize_segment)
    
    # 2. Extract standardized review classification
    review_info = df["notes"].apply(extract_review_reason)
    df["profile_review_required"] = review_info.apply(lambda x: x[0])
    df["profile_review_code"] = review_info.apply(lambda x: x[1])
    df["profile_review_label"] = review_info.apply(lambda x: x[2])
    df["profile_matched_keyword"] = review_info.apply(lambda x: x[3])
    df["profile_review_question"] = review_info.apply(lambda x: x[4])
    
    # Compatibility aliases
    df["fit_review_required"] = df["profile_review_required"]
    df["fit_review_code"] = df["profile_review_code"]
    df["fit_review_label"] = df["profile_review_label"]
    
    # 3. Clean domain formatting
    df["domain"] = df["domain"].fillna("")
    
    # 4. Verify Sinopec date strings preserved
    sinopec_dates = df[df["company"] == "Sinopec"]["trigger_date"].tolist()
    print("Preserved Sinopec date values:", sinopec_dates)
    
    # 5. Disambiguate tiers: rename retained Wingman tier to source_tier
    df["source_tier"] = df["tier"]
    
    # 6. Drop sensitive / internal columns (purging pattern_report_url and notes)
    columns_to_keep = [
        "company",
        "segment",
        "domain",
        "source_tier",
        "trigger_type",
        "trigger_date",
        "trigger_summary",
        "trigger_source_url",
        "scanned_at",
        "profile_review_required",
        "profile_review_code",
        "profile_review_label",
        "profile_matched_keyword",
        "profile_review_question",
        "fit_review_required",
        "fit_review_code",
        "fit_review_label",
    ]
    
    sanitized_df = df[columns_to_keep].copy()
    
    # Assert row and company preservation
    assert len(sanitized_df) == initial_rows == 1180
    assert sanitized_df["company"].nunique() == initial_companies == 785
    assert "notes" not in sanitized_df.columns
    assert "pattern_report_url" not in sanitized_df.columns
    
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    sanitized_df.to_csv(OUTPUT_PATH, index=False, encoding="utf-8")
    print(f"Successfully generated sanitized dataset at: {OUTPUT_PATH}")
    print(f"Sanitized rows: {len(sanitized_df)}, Unique companies: {sanitized_df['company'].nunique()}")
    print("Review reason distribution:")
    print(sanitized_df.groupby(["fit_review_code", "fit_review_label"])["company"].nunique())

if __name__ == "__main__":
    main()
