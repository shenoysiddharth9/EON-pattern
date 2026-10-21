# EON Pattern Report - Manual Review Workbook

This review workbook details every extracted record alongside its verbatim source evidence and PDF page number.

## Unknown (COMP-TMP-DDA35B)

- **Source File**: `Kinder-Morgan-Pattern-Report-4.pdf`
- **Wingman Tier**: `UNASSIGNED` (`NOT_PROVIDED`)
- **Manual Review Required**: `TRUE`
- **Manual Review Notes**: line_of_work: PARSING_FAILED - Line of work card and description pattern not found | forward_signals_count: DISCREPANCY - Report build statistics state 6 forward-looking press accounts, but only 4 cards are rendered under 'WHAT YOU ARE BUILDING'. | PARSING_FAILED: One or more fields failed extraction. | 11 public press account(s) are unverified by regulator. | Analyst normalization applied to profile field(s): headquarters_country

### 1. Standardized Field Audit Trail

| Field Name | Report Native Value | Standardized Value | Page | Confidence | Status | Analyst Assigned | Source Evidence |
| :--- | :--- | :--- | :---: | :---: | :---: | :---: | :--- |
| `company_name` | `Unknown` | `Unknown` | 1 | HIGH | `VALID` | NO | Header on Page 1: 'Unknown' |
| `report_window` | `2015–2024` | `2015-2024` | 1 | HIGH | `VALID` | NO | Page 1 card: '2015–2024' Window examined |
| `records_proven` | `0` | `0` | 1 | HIGH | `EXPLICIT_ZERO` | NO | Page 1 card: '0 Records proven' |
| `official_records_availability` | `Card not present in header (Card is '0 Records proven')` | `NOT_REPORTED` | - | HIGH | `MISSING_NOT_REPORTED` | NO | Header contains 'Records proven: 0' card, but no 'Official records reachable' card. Registry search does not establish organization-level record reachability. |
| `registry_search_status` | `OSHA, CSB, HSE registries searched` | `SEARCH_EXECUTED` | 9 | HIGH | `VALID` | NO | Page 9 build stats: 'OSHA: 0 inspection(s) found' |
| `official_company_record_found` | `0 confirmed inspection(s) carried citations and became claims` | `FALSE` | 9 | HIGH | `VALID` | NO | Page 9 build stats: '0 confirmed inspection(s) carried citations and became claims' |
| `public_sources_cited` | `1` | `1` | 1 | HIGH | `VALID` | NO | Page 1 card: '1 Public sources cited' |
| `header_publicly_written_accounts` | *[Empty]* | *[Empty]* | - | HIGH | `MISSING_NOT_REPORTED` | NO | Card 'Publicly written accounts' not present in report header |
| `answered_by_record` | `0/7` | `0/7` | 1 | HIGH | `VALID` | NO | Page 1 card: '0/7 Answered by your record' |
| `header_basis_of_report` | `Three kinds of public document` | `Public sources` | 1 | HIGH | `VALID` | YES | Page 1 text: 'Three kinds of public document, and nothing else.' |
| `headquarters_city` | `Houston` | `Houston` | 1 | HIGH | `VALID` | NO | Page 1 card: 'Houston' above 'head office' |
| `report_geography` | *[Empty]* | *[Empty]* | - | HIGH | `MISSING_NOT_REPORTED` | NO | No 'where they are from' card present on Page 2 |
| `headquarters_country` | `United States` | `United States` | 1 | HIGH | `VALID` | YES | Page 1 text: 'American paints and coatings company based in Cleveland, Ohio.' |
| `operating_countries` | *[Empty]* | *[Empty]* | - | HIGH | `MISSING_NOT_REPORTED` | NO | Operating countries not mentioned in report text |
| `year_founded` | `1997` | `1997` | 1 | HIGH | `VALID` | NO | Page 1 card: '1997' above 'founded' |
| `people_employed` | `11,075` | `11075` | 1 | HIGH | `VALID` | NO | Page 1 card: '11,075 people employed' |
| `line_of_work` | *[Empty]* | *[Empty]* | - | LOW | `PARSING_FAILED` | NO | Line of work not identified |
| `citations_count` | `0` | `0` | 3 | HIGH | `EXPLICIT_ZERO` | NO | Page 3 metric card: '0 citations' |
| `penalties_display_text` | `$0` | `$0` | 3 | HIGH | `EXPLICIT_ZERO` | NO | Page 3 metric card: '$0 in penalties' |
| `penalties_amount` | `0` | `0` | 3 | HIGH | `EXPLICIT_ZERO` | NO | Page 3 metric card: '$0' penalty amount |
| `penalties_currency_symbol` | `$` | `$` | 3 | HIGH | `VALID` | NO | Page 3 penalty symbol: '$' |
| `penalties_currency_iso` | `$` | `USD` | 3 | HIGH | `VALID` | YES | Page 3 symbol '$' mapped to ISO 'USD' supported by corporate US context |
| `investigated_accidents_count` | `0` | `0` | 3 | HIGH | `EXPLICIT_ZERO` | NO | Page 3 metric card: '0 investigated accidents' |
| `deaths_count` | `0` | `0` | 3 | HIGH | `EXPLICIT_ZERO` | NO | Page 3 'The shape of the record' card: '0 deaths' |
| `open_information_count` | `5` | `5` | 9 | HIGH | `VALID` | NO | Page 9 build stats: 'Open information: 5 publicly written account(s) found.' |
| `press_reported_account_count` | `6` | `6` | 9 | HIGH | `VALID` | NO | Page 9 build stats: 'Press: 6 reported accounts found.' |
| `forward_looking_press_count` | `6` | `6` | 9 | HIGH | `VALID` | NO | Page 9 build stats: 'Press: 6 accounts of what they are building or hiring for.' |
| `osha_inspections_found` | `0` | `0` | 9 | HIGH | `EXPLICIT_ZERO` | NO | Page 9 build stats: 'OSHA: 0 inspection(s) found' |
| `csb_mentions_found` | `0` | `0` | 9 | HIGH | `EXPLICIT_ZERO` | NO | Page 9 build stats: 'CSB: ... 0 mention this company.' |
| `sec_annual_report_status` | `read the 10-K filed 2026-02-13` | `10-K read` | 9 | HIGH | `VALID` | YES | Page 9 statement: '10-K filed 2026-02-13' |
| `sec_filing_date` | `2026-02-13` | `2026-02-13` | 9 | HIGH | `VALID` | NO | Page 9 10-K filing date: '2026-02-13' |
| `the_seven_answered_count` | `0` | `0` | 4 | HIGH | `EXPLICIT_ZERO` | NO | Page 4 'The Seven': dynamically computed from 7 individually extracted pattern records: 0 of 7 answered (all 7 state 'YOUR RECORD IS SILENT') |
| `the_seven_overall_status` | `YOUR RECORD IS SILENT` | `YOUR RECORD IS SILENT` | 4 | HIGH | `VALID` | NO | Page 4 'The Seven': confirmed all 7 extracted pattern statuses state 'YOUR RECORD IS SILENT' |
| `forward_signals_reported_count` | `6` | `6` | 9 | HIGH | `VALID` | NO | Report build statistics state: 'Press: 6 accounts of what they are building or hiring for' |
| `forward_signals_extracted_count` | `4` | `4` | - | HIGH | `VALID` | NO | Extracted 4 cards rendered under 'WHAT YOU ARE BUILDING' section |
| `forward_signals_count_matches` | `FALSE` | `FALSE` | - | HIGH | `VALID` | NO | Reconciliation: extracted 4 vs reported 6 |
| `public_accounts_reported_count` | `11` | `11` | 9 | HIGH | `VALID` | NO | Reported total publicly written accounts: 11 |
| `public_accounts_extracted_count` | `11` | `11` | - | HIGH | `VALID` | NO | Extracted 11 accounts rendered under 'What is publicly written*' |
| `public_accounts_count_matches` | `TRUE` | `TRUE` | - | HIGH | `VALID` | NO | Reconciliation: extracted 11 vs reported 11 |
| `seven_patterns_reported_count` | `7` | `7` | - | HIGH | `VALID` | NO | Report structure defines exactly 7 standard failure mode patterns ('The Seven'). |
| `seven_patterns_extracted_count` | `7` | `7` | - | HIGH | `VALID` | NO | Extracted 7 failure mode patterns from report text |
| `seven_patterns_count_matches` | `TRUE` | `TRUE` | - | HIGH | `VALID` | NO | Reconciliation: extracted 7 vs reported 7 |
| `safety_performance_inference` | `No conclusive pattern can be drawn from this record. That is a statement about what the public sources say, not a statement that the operation is safe.` | `CANNOT_INFER_SAFE (Absence of regulatory records does not imply safe operation)` | 3 | HIGH | `STANDARDIZED_ASSERTION` | YES | Extracted verbatim from report text: 'No conclusive pattern can be drawn from this record. That is a statement about what the public sources say, not a statement that the operation is safe.' |
| `regulatory_record_status` | `This is the foundation rather than a finding. Nothing has been proven about this organisation — it is where the conversation begins when the public record is silent.` | `Thin Case — No official safety records found` | 2 | HIGH | `STANDARDIZED_ASSERTION` | YES | Extracted verbatim from Page 2 'Thin Case' section: 'This is the foundation rather than a finding. Nothing has been proven about this organisation — it is where the conversation begins when the public record is silent.' |
| `report_audit_status` | `not reviewed` | `not reviewed` | 10 | HIGH | `VALID` | NO | Page 10 footer: 'Status of this copy: not reviewed' |

### 2. Forward Signals (WHAT YOU ARE BUILDING)

| Signal ID | Page | Reported By | Headline | Implication |
| :--- | :---: | :--- | :--- | :--- |
| `SIG-TMPDDA3-01` | 2 | pgjonline | FERC approves $5-B Kinder Morgan pipeline expansion to boost Southeast gas supply | Shown because of what it implies about the work ahead, not as a fact we have proven. |
| `SIG-TMPDDA3-02` | 2 | Yahoo Finance | Kinder Morgan (KMI) Stock May Be 39% Undervalued After Gas Expansion News | Shown because of what it implies about the work ahead, not as a fact we have proven. |
| `SIG-TMPDDA3-03` | 2 | TIKR | Kinder Morgan Stock Has $20B in Pipeline Expansion Ahead. Is the Growth Priced In? | Shown because of what it implies about the work ahead, not as a fact we have proven. |
| `SIG-TMPDDA3-04` | 2 | Midland Reporter-Telegram | Kinder Morgan places Gulf Coast Express expansion in service | Shown because of what it implies about the work ahead, not as a fact we have proven. |

### 3. Publicly Written Accounts

| Account ID | Page | Year | Tag | Outlet | Headline | Snippet |
| :--- | :---: | :---: | :--- | :--- | :--- | :--- |
| `ACC-TMPDDA3-01` | 7 | - | explosion or fire | Open source / news | List of pipeline accidents in the United States in the 2010s | forced to shut down. August 17 – Kinder Morgan's Natural Gas Pipeline Company of America had a flash fire and explosion ... |
| `ACC-TMPDDA3-02` | 7 | 2005 | explosion or fire | Open source / news | List of pipeline accidents in the United States in the 2000s | Administration) cited Kinder Morgan for failure to accurately mark or map the pipeline location. In 2005, the California... |
| `ACC-TMPDDA3-03` | 7 | - | explosion or fire | Open source / news | Petroleum industry in Canada | Burnaby Refinery in the Vancouver suburb of Burnaby processes 55,000 barrels per day (8,700 m3/d) of light oil received ... |
| `ACC-TMPDDA3-04` | 7 | - | workers killed | Open source / news | Kinder Morgan Energy Partners | Kinder Morgan Energy Partners LP (NYSE: KMI) (KMEP) is a subsidiary of Kinder Morgan, Inc. The company, which is classif... |
| `ACC-TMPDDA3-05` | 7 | 2016 | workers killed | Open source / news | List of pipeline accidents | Cameron Langford, "Kinder Morgan on Hook for Blast That Killed 22," Courthouse News Service, July 15, 2016, accessed 201... |
| `ACC-TMPDDA3-06` | 7 | 2025 | Fire | pgjonline | Kinder Morgan Pipeline Rupture in Wyoming Sparks Massive Fire, Halts Train | organisation. |
| `ACC-TMPDDA3-07` | 8 | 2025 | explosion | county10 | Kinder Morgan gas company investigating July 31 gas meter station explosion near Lysite | organisation. |
| `ACC-TMPDDA3-08` | 8 | 2020 | Spill | KUT | Kinder Morgan Sued Over Drilling Fluid Spill In Blanco County |  |
| `ACC-TMPDDA3-09` | 8 | 2021 | fire | Reuters | Kinder Morgan says Arizona natural gas pipeline fire extinguished, 2 dead |  |
| `ACC-TMPDDA3-10` | 8 | 2020 | explosion | KLBK | KAMC | EverythingLubbock | Snyder VFD responds to explosion near Kinder Morgan Gas Plant | a fact about your organisation. |
| `ACC-TMPDDA3-11` | 8 | 2023 | explosion | Lubbock Avalanche-Journal | Snyder Kinder Morgan plant experiences power failure, explosion | your organisation. |

### 4. The Seven Failure Mode Patterns

| Pattern ID | Num | Pattern Name | Company Record Status | Closed By | Benchmark Source | Quote |
| :--- | :---: | :--- | :--- | :--- | :--- | :--- |
| `PAT-TMPDDA3-01` | 01 | NEVER PRACTISED | `YOUR RECORD IS SILENT` | Genesis + EON Universal | IOGP, Safety Performance Indicators, 2024 data. | "The crew was doing this procedure for the first time, at the equipment." |
| `PAT-TMPDDA3-02` | 02 | LOST EXPERIENCE | `YOUR RECORD IS SILENT` | EON Tacit |  | "The person who knew how to do it that way retired in March." |
| `PAT-TMPDDA3-03` | 03 | WHEN THINGS GO WRONG | `YOUR RECORD IS SILENT` | Situation Room + EON Live | International Journal of share of causes. | "They have only ever practised it going right. Nobody rehearses the bad day." |
| `PAT-TMPDDA3-04` | 04 | TOLD, NOT TESTED | `YOUR RECORD IS SILENT` | Assess IQ + Competence IQ | International Journal of share of causes. | "We told them, but we never verified they could actually do it." |
| `PAT-TMPDDA3-05` | 05 | THE PLAN DIDN'T MATCH THE JOB | `YOUR RECORD IS SILENT` | Permit IQ | International Journal of share of causes. | "The permit did not cover the entire job, and nobody verified the isolation." |
| `PAT-TMPDDA3-06` | 06 | NO GUIDANCE IN THE MOMENT | `YOUR RECORD IS SILENT` | Field IQ / Edge | IOGP, Safety Performance Indicators, 2024 data. | "He skipped a step, on the wrong asset, and nobody saw it." |
| `PAT-TMPDDA3-07` | 07 | THE SAME MISTAKE AGAIN | `YOUR RECORD IS SILENT` | Compound IQ + Distillery | Kimberlite International Oilfield benchmark, 2023. Offshore benchmark. Do not present as an onshore figure. | "It happened before. Nothing changed. So it happened again." |

### 5. Logged Discrepancies & Ambiguities

| Issue ID | Field Name | Type | Description | Report Fragment | Proposed Resolution |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `ISS-TMPDDA3-01` | `line_of_work` | `PARSING_FAILED` | Line of work card and description pattern not found | E O N  A I  V E N T U R E S    ·    T H E  P A T T E R N  R E P O R T
Kinder Morgan
Your own safety record, assembled in one place — and set beside what
you have said publicly about the work ahead.
2015–2024
Window examined
1
Public sources cited
0
Records proven
0/7
Answered by your record
WHERE TH | Review company description. |
| `ISS-TMPDDA3-02` | `forward_signals_count` | `DISCREPANCY` | Report build statistics state 6 forward-looking press accounts, but only 4 cards are rendered under 'WHAT YOU ARE BUILDING'. | Page 2 has 4 cards; Page 8/10 states 'Press: 6 accounts of what they are building or hiring for.' | Preserve 4 extracted signals; flag 2 unaccounted background signals for analyst verification. |

---

