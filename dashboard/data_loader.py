"""
Data loader module for EON Pattern Extractor Dashboard.
Provides cached access to baseline and holdout extraction datasets with scope switching.
"""

from pathlib import Path
from typing import Dict
import streamlit as st
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
BASELINE_DIR = PROJECT_ROOT / "output"
HOLDOUT_DIR = PROJECT_ROOT / "output" / "holdout_v1_1"

DATASET_FILENAMES = {
    "companies": "companies_summary.csv",
    "evidence": "field_evidence.csv",
    "signals": "forward_signals.csv",
    "accounts": "public_accounts.csv",
    "patterns": "seven_patterns.csv",
    "issues": "validation_issues.csv",
}


def _read_csv_safe(path: Path) -> pd.DataFrame:
    """Read CSV file if it exists, otherwise return empty DataFrame."""
    if path.exists() and path.stat().st_size > 0:
        return pd.read_csv(path)
    return pd.DataFrame()


@st.cache_data(show_spinner="Loading extraction datasets...")
def load_scope_data(scope: str) -> Dict[str, pd.DataFrame]:
    """
    Load data according to selected scope:
      - 'Baseline Reports': Baseline reports (Sherwin-Williams, Reliance, ExxonMobil) from output/
      - 'Audited Holdout Report': Audited holdout (Kinder Morgan) from output/holdout_v1_1/
      - 'Combined View': All 4 reports combined
    """
    baseline_dfs = {k: _read_csv_safe(BASELINE_DIR / fname) for k, fname in DATASET_FILENAMES.items()}
    holdout_dfs = {k: _read_csv_safe(HOLDOUT_DIR / fname) for k, fname in DATASET_FILENAMES.items()}

    if scope == "Audited Holdout Report":
        return holdout_dfs

    if scope == "Baseline Reports":
        return baseline_dfs

    # Combined View
    combined = {}
    dedup_keys = {
        "companies": "company_id",
        "evidence": ["company_id", "field_name"],
        "signals": "signal_id",
        "accounts": "account_id",
        "patterns": "pattern_id",
        "issues": "issue_id",
    }

    for k in DATASET_FILENAMES:
        b_df = baseline_dfs.get(k, pd.DataFrame())
        h_df = holdout_dfs.get(k, pd.DataFrame())
        if b_df.empty and h_df.empty:
            combined[k] = pd.DataFrame()
        elif b_df.empty:
            combined[k] = h_df.copy()
        elif h_df.empty:
            combined[k] = b_df.copy()
        else:
            cat_df = pd.concat([b_df, h_df], ignore_index=True)
            key = dedup_keys.get(k)
            if key and (isinstance(key, str) and key in cat_df.columns) or (isinstance(key, list) and all(c in cat_df.columns for c in key)):
                cat_df = cat_df.drop_duplicates(subset=key, keep="last")
            combined[k] = cat_df

    return combined
