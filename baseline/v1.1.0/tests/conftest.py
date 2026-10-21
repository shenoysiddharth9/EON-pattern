"""
Pytest configuration and fixtures.
"""
import sys
from pathlib import Path
import pytest

project_root = Path(__file__).resolve().parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from src.pipeline import run_pipeline
from src.models import CompanyRecord

@pytest.fixture(scope="session")
def extracted_records():
    input_dir = project_root / "input"
    output_dir = project_root / "output"
    records = run_pipeline(input_dir=input_dir, output_dir=output_dir)
    return {r.company_name: r for r in records}
