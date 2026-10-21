# EON Pattern Report Standardized Field Extractor

A robust, audited Python extraction pipeline that extracts standardized company-level fields and granular evidence from EON Pattern Report PDFs.

## Supported Reports
- `Sherwin-Williams Pattern Report.pdf` (Wingman Tier 3)
- `Reliance (RIL) Pattern Report.pdf` (Wingman Tier 2)
- `ExxonMobil Pattern Report.pdf` (Wingman Tier 1)

## Key Architectural & Policy Guarantees
1. **Zero vs. Missing**: Preserves absent fields as missing (empty string) rather than coercing into `0`. Explicit report zeros are retained as numeric `0` with `EXPLICIT_ZERO` validation status.
2. **Safety Non-Inference**: Explicitly enforces `CANNOT_INFER_SAFE`. Regulatory record silence is never translated into positive safety assertions.
3. **Categorical Records Reachability**: "None official records reachable" is maintained as categorical `"None"`, never numeric `0`.
4. **Wingman Segregation**: Manual Trigger Board tiers (`Tier 1`, `Tier 2`, `Tier 3`) are attributed to `manual_from_trigger_board` and segregated from PDF-extracted fields.
5. **No Concatenation of Repeating Items**: Press signals, public accounts, and failure mode patterns are stored one row per item across dedicated relational CSVs.

## Output CSVs (Generated in `output/`)
1. `companies_summary.csv`: One standardized row per company (41 columns).
2. `field_evidence.csv`: Granular field audit trail (99 rows: verbatim quotes, page numbers, confidence, validation status, analyst assignment flag).
3. `forward_signals.csv`: One row per signal from "WHAT YOU ARE BUILDING" (12 rows).
4. `public_accounts.csv`: One row per account from "What is publicly written*" (21 rows).
5. `seven_patterns.csv`: One row per failure mode pattern (01 to 07) per company (21 rows).
6. `validation_issues.csv`: Tracked ambiguities, discrepancies, and manual review triggers (4 rows).

## Running Extraction & Tests
```bash
# Run extraction
python3 run_extraction.py

# Run test suite
python3 -m pytest -v tests/
```
