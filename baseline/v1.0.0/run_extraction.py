#!/usr/bin/env python3
"""
CLI entry point to execute the EON Pattern Report extraction pipeline.
"""
import sys
from pathlib import Path

# Add project root to python path
project_root = Path(__file__).resolve().parent
sys.path.insert(0, str(project_root))

from src.pipeline import run_pipeline

def main():
    input_dir = project_root / "input"
    output_dir = project_root / "output"
    print("==========================================================")
    print("      EON PATTERN REPORT STANDARDIZED EXTRACTOR           ")
    print("==========================================================")
    records = run_pipeline(input_dir=input_dir, output_dir=output_dir)
    print("==========================================================")
    print(f"Extraction complete for {len(records)} companies.")
    print(f"Outputs written to: {output_dir}")
    print("==========================================================")

if __name__ == "__main__":
    main()
