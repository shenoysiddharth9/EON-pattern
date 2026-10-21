# Wingman Scan Converter Guide

Standalone offline utility to convert Wingman company-scan JSON exports into the canonical CSV format required by the Streamlit dashboard.

---

## 1. Supported Input Structures

The converter accepts two JSON formats:

### A. Confirmed API Response (`GET /api/scans`)
The standard wrapped response payload from `GET /api/scans`:
```json
{
  "ok": true,
  "scans": [
    {
      "id": 101,
      "company": "Apex Energy Systems",
      "segment": "oil and gas",
      "tier": 1,
      "triggers": [
        {
          "type": "project_fid_commissioning",
          "value": "Approved final investment decision for LNG liquefaction train expansion.",
          "source": "https://example.com/press/apex-lng-fid-announcement",
          "date": "2026-08-15"
        }
      ],
      "notes": "Operator profile confirmed.",
      "scanned_at": "2026-09-15T14:22:10.450Z",
      "contacts_held": 12
    }
  ]
}
```

### B. Top-Level Array Export
Direct database exports or array dumps where the top-level entity is a JSON array of scan objects:
```json
[
  {
    "company": "Beacon Chemical Technologies",
    "segment": "chemicals",
    "tier": 2,
    "triggers": [...],
    "scanned_at": "2026-09-12T09:15:00.120Z"
  }
]
```

*Note: Any other top-level format (including `{"ok": false, ...}` or non-object entries) is rejected.*

---

## 2. Command Usage

Run the converter from your terminal:

```bash
python scripts/convert_wingman_scans.py \
  --input wingman-scans.json \
  --output wingman-dashboard.csv
```

### Options
- `--input`, `-i`: Path to the source JSON file (*required*).
- `--output`, `-o`: Path to the output CSV file (*required*).

---

## 3. Output CSV Format

The output CSV strictly conforms to the dashboard's 9 canonical columns in the following deterministic order:

| Column Header | Type | Description |
| :--- | :--- | :--- |
| `company` | String | Normalized company name (formula-injection sanitized). |
| `segment` | String | Standardized industry sector (defaults to `"Diversified Industrial / Unspecified"` if omitted). |
| `domain` | String | Clean website domain (or blank if omitted from scan). |
| `source_tier` | Integer string (`"1"`, `"2"`, `"3"`) | Static Wingman export tier metadata. |
| `trigger_type` | Category string | One of the 8 canonical trigger categories (or blank for zero-trigger accounts). |
| `trigger_date` | Date (`YYYY-MM-DD`) | Event date (or blank if undated in scan). |
| `trigger_summary` | String | Operational description (formula-injection sanitized). |
| `trigger_source_url` | String | Web URL or publication citation (formula-injection sanitized). |
| `scanned_at` | Date (`YYYY-MM-DD`) | UTC calendar date from scan timestamp. |

### Data Exclusions
The converter strictly excludes:
- `id`
- `notes`
- `contacts_held` (reported only in the console summary)
- Any contact data, CRM ownership, or suppression records.

---

## 4. Warning and Failure Behavior

### Blocking Validation (Exit Code 1)
The converter halts and exits with code 1 if any of the following occur:
- Malformed JSON.
- Unsupported top-level structure (`ok` is false, missing `scans`, etc.).
- Non-object scan records.
- Missing or blank `company`.
- Duplicate company names after case-insensitive normalization.
- Invalid `tier` (must be integer 1, 2, or 3).
- Non-array, non-null `triggers`.
- Non-object trigger items.
- Unknown trigger `type` (must be one of the 8 canonical categories).
- Invalid nonblank `date` (must match valid `YYYY-MM-DD`).
- Invalid nonblank `scanned_at` (must be parseable ISO 8601).

### Non-Blocking Warnings
The conversion succeeds with logged warnings for:
- Null trigger dates (exported as blank `""`).
- Null trigger arrays (normalized to `[]`).
- Missing or empty segments (fallback to `"Diversified Industrial / Unspecified"`).
- Plain-text citation sources (preserved as safe text audit records).
- Missing domain fields (exported as blank `""`).

---

## 5. Offline Isolation and Security Guarantees

1. **Fully Offline Execution**:
   - Zero outbound HTTP/HTTPS API calls.
   - Zero database connections.
   - Zero reads from environment variables or Streamlit secrets (`st.secrets`).
   - Zero token or credential handling.
   - Zero modifications to the input JSON or default dataset.
2. **Spreadsheet Formula-Injection Protection (CWE-1236 / OWASP)**:
   - Any cell beginning with `=`, `+`, `-`, `@`, `\t`, `\r`, or `\n` is automatically prepended with a single quote (`'`) to disable formula execution in Excel or Google Sheets.
3. **Deterministic Output**:
   - Companies are sorted case-insensitively.
   - Triggers preserve array order.
   - Output uses standard UTF-8 encoding with explicit LF line terminators.

---

## 6. Tier Semantics: `source_tier` vs Displayed Dynamic Tier

> [!IMPORTANT]
> `source_tier` is **not** the displayed dashboard tier.
>
> - **`source_tier`**: Static metadata recorded by Wingman during initial scan based on stored trigger counts.
> - **`computed_tier`**: Dynamic tier recalculated in real time by the dashboard engine based on:
>   - Active distinct trigger categories.
>   - Selected Analysis As-Of date.
>   - Configured category expiry windows.
>
> It is normal and expected for an account with `source_tier: Tier 2` to display as **Monitor / Nurture (Tier 3)** if its triggers are expired or undated, or for a multi-catalyst account to be classified dynamically.

---

## 7. Evidence-Link Safety & Plain-Text Citations

In the dashboard:
- **Valid URLs** (`http://...`, `https://...`): Tested against client-side syntactic safety rules (blocking private IPs, localhost, file paths) and rendered as clickable external links with `target="_blank" rel="noopener noreferrer"`.
- **Plain-Text Citations** (e.g. `"Industrial Info Resources Bulletin"`): Detected as non-URLs and rendered safely as non-clickable monospace text blocks (`<code>`). They are never discarded or broken.

---

## 8. Uploading into the Streamlit Dashboard (Custom CSV Mode)

Once generated, the CSV can be analyzed in the dashboard:

1. Launch the Streamlit application:
   ```bash
   streamlit run app.py
   ```
2. Navigate to the sidebar control panel under **📂 Dataset Selection**.
3. Upload the generated CSV file into the **Custom CSV Upload** widget.
4. The dashboard will automatically validate schema conformity and display a validation preview.
5. Review the Analysis As-Of date (pre-populated with the latest valid `scanned_at` date).
6. Click **🚀 Use This Dataset** to activate custom mode.
7. All three pages (**Portfolio Insights**, **Company Browser**, **Company Ranker**) will instantly update to reflect the converted dataset.
8. To return to baseline, click **🔄 Return to Default Dataset** at any time. The baseline Wingman dataset remains completely untouched.
