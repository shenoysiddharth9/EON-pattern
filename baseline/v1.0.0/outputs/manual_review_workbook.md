# EON Pattern Report - Manual Review Workbook

This review workbook details every extracted record alongside its verbatim source evidence and PDF page number.

## Sherwin-Williams (COMP-SHW)

- **Source File**: `Sherwin-Williams Pattern Report.pdf`
- **Wingman Tier**: `Tier 3` (`manual_from_trigger_board`)
- **Manual Review Required**: `TRUE`
- **Manual Review Notes**: people_employed: AMBIGUITY - Headcount card is absent on Page 1; extracted 64,249 from SEC 10-K quote on Page 7. | line_of_work: AMBIGUITY - Sherwin-Williams lacks Page 2 'line of work' card; extracted from Page 1 narrative text. | forward_signals_count: DISCREPANCY - Report build statistics state 6 forward-looking press accounts, but only 4 cards are rendered under 'WHAT YOU ARE BUILDING'. | 7 public press account(s) are unverified by regulator. | Analyst normalization applied to profile field(s): headquarters_country, line_of_work

### 1. Standardized Field Audit Trail

| Field Name | Report Native Value | Standardized Value | Page | Confidence | Status | Analyst Assigned | Source Evidence |
| :--- | :--- | :--- | :---: | :---: | :---: | :---: | :--- |
| `company_name` | `Sherwin-Williams` | `Sherwin-Williams` | 1 | HIGH | `VALID` | NO | Header on Page 1: 'Sherwin-Williams' |
| `report_window` | `2015–2024` | `2015-2024` | 1 | HIGH | `VALID` | NO | Page 1 card: '2015–2024' Window examined |
| `records_proven` | `0` | `0` | 1 | HIGH | `EXPLICIT_ZERO` | NO | Page 1 card: '0 Records proven' |
| `official_records_availability` | `Card not present in header (Card is '0 Records proven')` | `NOT_REPORTED` | - | HIGH | `MISSING_NOT_REPORTED` | NO | Header contains 'Records proven: 0' card, but no 'Official records reachable' card. Registry search does not establish organization-level record reachability. |
| `registry_search_status` | `OSHA, CSB, HSE registries searched` | `SEARCH_EXECUTED` | 10 | HIGH | `VALID` | NO | Page 10 build stats: 'OSHA: 0 inspection(s) found' |
| `official_company_record_found` | `0 confirmed inspection(s) carried citations and became claims` | `FALSE` | 10 | HIGH | `VALID` | NO | Page 10 build stats: '0 confirmed inspection(s) carried citations and became claims' |
| `public_sources_cited` | `1` | `1` | 1 | HIGH | `VALID` | NO | Page 1 card: '1 Public sources cited' |
| `header_publicly_written_accounts` | *[Empty]* | *[Empty]* | - | HIGH | `MISSING_NOT_REPORTED` | NO | Card 'Publicly written accounts' not present in report header |
| `answered_by_record` | `0/7` | `0/7` | 1 | HIGH | `VALID` | NO | Page 1 card: '0/7 Answered by your record' |
| `header_basis_of_report` | `Three kinds of public document` | `Public sources` | 1 | HIGH | `VALID` | YES | Page 1 text: 'Three kinds of public document, and nothing else.' |
| `headquarters_city` | `Cleveland` | `Cleveland` | 1 | HIGH | `VALID` | NO | Page 1 card: 'Cleveland' above 'head office' |
| `report_geography` | *[Empty]* | *[Empty]* | - | HIGH | `MISSING_NOT_REPORTED` | NO | No 'where they are from' card present on Page 2 |
| `headquarters_country` | `United States` | `United States` | 1 | HIGH | `VALID` | YES | Page 1 text: 'American paints and coatings company based in Cleveland, Ohio.' |
| `operating_countries` | `operations in over 120 countries` | `operations in over 120 countries` | 1 | HIGH | `VALID` | NO | Page 1 text: 'operations in over 120 countries' |
| `year_founded` | `1866` | `1866` | 1 | HIGH | `VALID` | NO | Page 1 card: '1866' above 'founded' |
| `people_employed` | `64,249` | `64249` | 7 | HIGH | `VALID` | NO | Page 7 annual filing quote: 'employed 64,249 people worldwide' |
| `line_of_work` | `paints and coatings` | `Paints and coatings` | 1 | MEDIUM | `VALID` | YES | Page 1 text: 'American paints and coatings company based in Cleveland, Ohio.' |
| `citations_count` | `0` | `0` | 3 | HIGH | `EXPLICIT_ZERO` | NO | Page 3 metric card: '0 citations' |
| `penalties_display_text` | `$0` | `$0` | 3 | HIGH | `EXPLICIT_ZERO` | NO | Page 3 metric card: '$0 in penalties' |
| `penalties_amount` | `0` | `0` | 3 | HIGH | `EXPLICIT_ZERO` | NO | Page 3 metric card: '$0' penalty amount |
| `penalties_currency_symbol` | `$` | `$` | 3 | HIGH | `VALID` | NO | Page 3 penalty symbol: '$' |
| `penalties_currency_iso` | `$` | `USD` | 3 | HIGH | `VALID` | YES | Page 3 symbol '$' mapped to ISO 'USD' supported by corporate US context |
| `investigated_accidents_count` | `0` | `0` | 3 | HIGH | `EXPLICIT_ZERO` | NO | Page 3 metric card: '0 investigated accidents' |
| `deaths_count` | `0` | `0` | 3 | HIGH | `EXPLICIT_ZERO` | NO | Page 3 'The shape of the record' card: '0 deaths' |
| `open_information_count` | `1` | `1` | 10 | HIGH | `VALID` | NO | Page 10 build stats: 'Open information: 1 publicly written account(s) found.' |
| `press_reported_account_count` | `6` | `6` | 10 | HIGH | `VALID` | NO | Page 10 build stats: 'Press: 6 reported accounts found.' |
| `forward_looking_press_count` | `6` | `6` | 10 | HIGH | `VALID` | NO | Page 10 build stats: 'Press: 6 accounts of what they are building or hiring for.' |
| `osha_inspections_found` | `0` | `0` | 10 | HIGH | `EXPLICIT_ZERO` | NO | Page 10 build stats: 'OSHA: 0 inspection(s) found' |
| `csb_mentions_found` | `0` | `0` | 10 | HIGH | `EXPLICIT_ZERO` | NO | Page 10 build stats: 'CSB: ... 0 mention this company.' |
| `sec_annual_report_status` | `read the 10-K filed 2026-02-19` | `10-K read` | 10 | HIGH | `VALID` | YES | Page 10 statement: '10-K filed 2026-02-19' |
| `sec_filing_date` | `2026-02-19` | `2026-02-19` | 10 | HIGH | `VALID` | NO | Page 10 10-K filing date: '2026-02-19' |
| `the_seven_answered_count` | `0` | `0` | 5 | HIGH | `EXPLICIT_ZERO` | NO | Page 5 'The Seven': dynamically computed from 7 individually extracted pattern records: 0 of 7 answered (all 7 state 'YOUR RECORD IS SILENT') |
| `the_seven_overall_status` | `YOUR RECORD IS SILENT` | `YOUR RECORD IS SILENT` | 5 | HIGH | `VALID` | NO | Page 5 'The Seven': confirmed all 7 extracted pattern statuses state 'YOUR RECORD IS SILENT' |
| `forward_signals_reported_count` | `6` | `6` | 10 | HIGH | `VALID` | NO | Report build statistics state: 'Press: 6 accounts of what they are building or hiring for' |
| `forward_signals_extracted_count` | `4` | `4` | - | HIGH | `VALID` | NO | Extracted 4 cards rendered under 'WHAT YOU ARE BUILDING' section |
| `forward_signals_count_matches` | `FALSE` | `FALSE` | - | HIGH | `VALID` | NO | Reconciliation: extracted 4 vs reported 6 |
| `public_accounts_reported_count` | `7` | `7` | 10 | HIGH | `VALID` | NO | Reported total publicly written accounts: 7 |
| `public_accounts_extracted_count` | `7` | `7` | - | HIGH | `VALID` | NO | Extracted 7 accounts rendered under 'What is publicly written*' |
| `public_accounts_count_matches` | `TRUE` | `TRUE` | - | HIGH | `VALID` | NO | Reconciliation: extracted 7 vs reported 7 |
| `seven_patterns_reported_count` | `7` | `7` | - | HIGH | `VALID` | NO | Report structure defines exactly 7 standard failure mode patterns ('The Seven'). |
| `seven_patterns_extracted_count` | `7` | `7` | - | HIGH | `VALID` | NO | Extracted 7 failure mode patterns from report text |
| `seven_patterns_count_matches` | `TRUE` | `TRUE` | - | HIGH | `VALID` | NO | Reconciliation: extracted 7 vs reported 7 |
| `safety_performance_inference` | `No conclusive pattern can be drawn from this record. That is a statement about what the public sources say, not a statement that the operation is safe.` | `CANNOT_INFER_SAFE (Absence of regulatory records does not imply safe operation)` | 3 | HIGH | `STANDARDIZED_ASSERTION` | YES | Extracted verbatim from report text: 'No conclusive pattern can be drawn from this record. That is a statement about what the public sources say, not a statement that the operation is safe.' |
| `regulatory_record_status` | `This is the foundation rather than a finding. Nothing has been proven about this organisation — it is where the conversation begins when the public record is silent.` | `Thin Case — No official safety records found` | 2 | HIGH | `STANDARDIZED_ASSERTION` | YES | Extracted verbatim from Page 2 'Thin Case' section: 'This is the foundation rather than a finding. Nothing has been proven about this organisation — it is where the conversation begins when the public record is silent.' |
| `report_audit_status` | `not reviewed` | `not reviewed` | 11 | HIGH | `VALID` | NO | Page 11 footer: 'Status of this copy: not reviewed' |

### 2. Forward Signals (WHAT YOU ARE BUILDING)

| Signal ID | Page | Reported By | Headline | Implication |
| :--- | :---: | :--- | :--- | :--- |
| `SIG-SHW-01` | 2 | PR Newswire | Sherwin-Williams Positions Itself as the One Partner for Data Center Construction | Shown because of what it implies about the work ahead, not as a fact we have proven. |
| `SIG-SHW-02` | 2 | Yahoo Finance | Sherwin-Williams (SHW) Reports Record Q1 EBITDA on Sales Growth and Margin Expansion | Shown because of what it implies about the work ahead, not as a fact we have proven. |
| `SIG-SHW-03` | 2 | WBKO | Sherwin-Williams expands Bowling Green plant with automation, new jobs | Shown because of what it implies about the work ahead, not as a fact we have proven. |
| `SIG-SHW-04` | 2 | WNKY | Sherwin-Williams Bowling Green plant expands to meet roofing demands | Shown because of what it implies about the work ahead, not as a fact we have proven. |

### 3. Publicly Written Accounts

| Account ID | Page | Year | Tag | Outlet | Headline | Snippet |
| :--- | :---: | :---: | :--- | :--- | :--- | :--- |
| `ACC-SHW-01` | 8 | - | safety incident | Open source / news | Lead poisoning | the State of California against several companies decided against Sherwin-Williams, NL Industries, and ConAgra and order... |
| `ACC-SHW-02` | 8 | 2023 | injured | spectrumlocalnews | 1 person injured in explosion, fire at Garland Sherwin-Williams plant | your organisation. |
| `ACC-SHW-03` | 8 | 2024 | spills | Cleveland 19 News | Sherwin-Williams plant spills 100 gallons of diesel fuel into Cuyahoga River: Cleveland HAZMAT | organisation. |
| `ACC-SHW-04` | 8 | 2025 | fire | Signal Cleveland | Sherwin-Williams to fix fire protection problem on new headquarters | organisation. |
| `ACC-SHW-05` | 8 | 2025 | Fire | KSN | Fire at Sherwin-Williams plant in Andover is out | organisation. |
| `ACC-SHW-06` | 8 | 2023 | explosion | CBS News | About 600,000 gallons of potentially impacted water pumped out of creeks after Sherwin-Williams explosion | organisation. |
| `ACC-SHW-07` | 9 | 2023 | explosion | cnn | 1 hurt in explosion at a Sherwin-Williams paint factory plant in Texas | organisation. |

### 4. The Seven Failure Mode Patterns

| Pattern ID | Num | Pattern Name | Company Record Status | Closed By | Benchmark Source | Quote |
| :--- | :---: | :--- | :--- | :--- | :--- | :--- |
| `PAT-SHW-01` | 01 | NEVER PRACTISED | `YOUR RECORD IS SILENT` | Genesis + EON Universal | IOGP, Safety Performance Indicators, 2024 data. | "The crew was doing this procedure for the first time, at the equipment." |
| `PAT-SHW-02` | 02 | LOST EXPERIENCE | `YOUR RECORD IS SILENT` | EON Tacit |  | "The person who knew how to do it that way retired in March." |
| `PAT-SHW-03` | 03 | WHEN THINGS GO WRONG | `YOUR RECORD IS SILENT` | Situation Room + EON Live | International Journal of a share of causes. | "They have only ever practised it going right. Nobody rehearses the bad day." |
| `PAT-SHW-04` | 04 | TOLD, NOT TESTED | `YOUR RECORD IS SILENT` | Assess IQ + Competence IQ | International Journal of a share of causes. | "We told them, but we never verified they could actually do it." |
| `PAT-SHW-05` | 05 | THE PLAN DIDN'T MATCH THE JOB | `YOUR RECORD IS SILENT` | Permit IQ | International Journal of a share of causes. | "The permit did not cover the entire job, and nobody verified the isolation." |
| `PAT-SHW-06` | 06 | NO GUIDANCE IN THE MOMENT | `YOUR RECORD IS SILENT` | Field IQ / Edge | IOGP, Safety Performance Indicators, 2024 data. | "He skipped a step, on the wrong asset, and nobody saw it." |
| `PAT-SHW-07` | 07 | THE SAME MISTAKE AGAIN | `YOUR RECORD IS SILENT` | Compound IQ + Distillery | Kimberlite International operator benchmark, 2023. Offshore benchmark. Do not present as an onshore figure. | "It happened before. Nothing changed. So it happened again." |

### 5. Logged Discrepancies & Ambiguities

| Issue ID | Field Name | Type | Description | Report Fragment | Proposed Resolution |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `ISS-SHW-01` | `people_employed` | `AMBIGUITY` | Headcount card is absent on Page 1; extracted 64,249 from SEC 10-K quote on Page 7. | Page 7: 'employed 64,249 people worldwide' | Approve 10-K filing excerpt as authoritative headcount source. |
| `ISS-SHW-02` | `line_of_work` | `AMBIGUITY` | Sherwin-Williams lacks Page 2 'line of work' card; extracted from Page 1 narrative text. | Page 1: 'American paints and coatings company based in Cleveland, Ohio.' | Approve narrative text extraction as analyst-assigned. |
| `ISS-SHW-03` | `forward_signals_count` | `DISCREPANCY` | Report build statistics state 6 forward-looking press accounts, but only 4 cards are rendered under 'WHAT YOU ARE BUILDING'. | Page 2 has 4 cards; Page 8/10 states 'Press: 6 accounts of what they are building or hiring for.' | Preserve 4 extracted signals; flag 2 unaccounted background signals for analyst verification. |

---

## Reliance (RIL) (COMP-REL)

- **Source File**: `Reliance (RIL) Pattern Report.pdf`
- **Wingman Tier**: `Tier 2` (`manual_from_trigger_board`)
- **Manual Review Required**: `TRUE`
- **Manual Review Notes**: year_founded: MISSING_DATA - Founding year card absent in report | people_employed: MISSING_DATA - Headcount disclosure absent in report | 2 public press account(s) are unverified by regulator.

### 1. Standardized Field Audit Trail

| Field Name | Report Native Value | Standardized Value | Page | Confidence | Status | Analyst Assigned | Source Evidence |
| :--- | :--- | :--- | :---: | :---: | :---: | :---: | :--- |
| `company_name` | `Reliance (RIL)` | `Reliance (RIL)` | 1 | HIGH | `VALID` | NO | Header on Page 1: 'Reliance (RIL)' |
| `report_window` | `2015–2024` | `2015-2024` | 1 | HIGH | `VALID` | NO | Page 1 card: '2015–2024' Window examined |
| `records_proven` | *[Empty]* | *[Empty]* | - | HIGH | `MISSING_NOT_REPORTED` | NO | Card 'Records proven' not present in report header |
| `official_records_availability` | `None` | `NO_RECORD_REACHABLE` | 1 | HIGH | `CATEGORICAL_UNAVAILABLE` | NO | Page 1 card: 'None Official records reachable' |
| `registry_search_status` | `OSHA, CSB, HSE registries searched` | `SEARCH_EXECUTED` | 8 | HIGH | `VALID` | NO | Page 8 build stats: 'OSHA: 0 inspection(s) found' |
| `official_company_record_found` | `0 confirmed inspection(s) carried citations and became claims` | `FALSE` | 8 | HIGH | `VALID` | NO | Page 8 build stats: '0 confirmed inspection(s) carried citations and became claims' |
| `public_sources_cited` | *[Empty]* | *[Empty]* | - | HIGH | `MISSING_NOT_REPORTED` | NO | Card 'Public sources cited' not present in report header |
| `header_publicly_written_accounts` | `2` | `2` | 1 | HIGH | `VALID` | NO | Page 1 card: '2 Publicly written accounts' |
| `answered_by_record` | *[Empty]* | *[Empty]* | - | HIGH | `MISSING_NOT_REPORTED` | NO | Card 'Answered by your record' not present in report header |
| `header_basis_of_report` | `Open sources` | `Open sources` | 1 | HIGH | `VALID` | NO | Page 1 card: 'Open sources' under 'What this rests on' |
| `headquarters_city` | `Mumbai` | `Mumbai` | 1 | HIGH | `VALID` | NO | Page 1 text: 'headquartered in Mumbai' |
| `report_geography` | `India` | `India` | 2 | HIGH | `VALID` | NO | Page 2 card: 'India' above 'where they are from' |
| `headquarters_country` | `India` | `India` | 2 | HIGH | `VALID` | NO | Page 2 card 'where they are from': 'India' |
| `operating_countries` | *[Empty]* | *[Empty]* | - | HIGH | `MISSING_NOT_REPORTED` | NO | Operating countries not mentioned in report text |
| `year_founded` | *[Empty]* | *[Empty]* | - | HIGH | `MISSING_NOT_REPORTED` | NO | No 'founded' card or founding date found in report text |
| `people_employed` | *[Empty]* | *[Empty]* | - | HIGH | `MISSING_NOT_REPORTED` | NO | No employee count card or disclosure found in report |
| `line_of_work` | `Petrochemicals` | `Petrochemicals` | 2 | HIGH | `VALID` | NO | Page 2 card: 'Petrochemicals line of work' |
| `citations_count` | `0` | `0` | 3 | HIGH | `EXPLICIT_ZERO` | NO | Page 3 metric card: '0 citations' |
| `penalties_display_text` | `$0` | `$0` | 3 | HIGH | `EXPLICIT_ZERO` | NO | Page 3 metric card: '$0 in penalties' |
| `penalties_amount` | `0` | `0` | 3 | HIGH | `EXPLICIT_ZERO` | NO | Page 3 metric card: '$0' penalty amount |
| `penalties_currency_symbol` | `$` | `$` | 3 | HIGH | `VALID` | NO | Page 3 penalty symbol: '$' |
| `penalties_currency_iso` | `$` | *[Empty]* | 3 | LOW | `MISSING_NOT_REPORTED` | YES | Page 3 symbol '$' mapped to ISO '' supported by corporate US context |
| `investigated_accidents_count` | `0` | `0` | 3 | HIGH | `EXPLICIT_ZERO` | NO | Page 3 metric card: '0 investigated accidents' |
| `deaths_count` | `0` | `0` | 3 | HIGH | `EXPLICIT_ZERO` | NO | Page 3 'The shape of the record' card: '0 deaths' |
| `open_information_count` | `1` | `1` | 8 | HIGH | `VALID` | NO | Page 8 build stats: 'Open information: 1 publicly written account(s) found.' |
| `press_reported_account_count` | `1` | `1` | 8 | HIGH | `VALID` | NO | Page 8 build stats: 'Press: 1 reported accounts found.' |
| `forward_looking_press_count` | `4` | `4` | 8 | HIGH | `VALID` | NO | Page 8 build stats: 'Press: 4 accounts of what they are building or hiring for.' |
| `osha_inspections_found` | `0` | `0` | 8 | HIGH | `EXPLICIT_ZERO` | NO | Page 8 build stats: 'OSHA: 0 inspection(s) found' |
| `csb_mentions_found` | `0` | `0` | 8 | HIGH | `EXPLICIT_ZERO` | NO | Page 8 build stats: 'CSB: ... 0 mention this company.' |
| `sec_annual_report_status` | `This organisation files no annual report with the SEC — it is private, foreign-listed, or a subsidiary that reports through a parent` | `No annual report with SEC / private or foreign-listed` | 6 | HIGH | `VALID` | YES | Page 6 section 'In your own words': 'This organisation files no annual report with the SEC — it is private, foreign-listed, or a subsidiary that reports through a parent' |
| `sec_filing_date` | *[Empty]* | *[Empty]* | - | HIGH | `MISSING_NOT_REPORTED` | NO | No readable 10-K filing date present in report |
| `the_seven_answered_count` | `0` | `0` | 5 | HIGH | `EXPLICIT_ZERO` | NO | Page 5 'The Seven': dynamically computed from 7 individually extracted pattern records: 0 of 7 answered (all 7 state 'YOUR RECORD IS SILENT') |
| `the_seven_overall_status` | `YOUR RECORD IS SILENT` | `YOUR RECORD IS SILENT` | 5 | HIGH | `VALID` | NO | Page 5 'The Seven': confirmed all 7 extracted pattern statuses state 'YOUR RECORD IS SILENT' |
| `forward_signals_reported_count` | `4` | `4` | 8 | HIGH | `VALID` | NO | Report build statistics state: 'Press: 4 accounts of what they are building or hiring for' |
| `forward_signals_extracted_count` | `4` | `4` | - | HIGH | `VALID` | NO | Extracted 4 cards rendered under 'WHAT YOU ARE BUILDING' section |
| `forward_signals_count_matches` | `TRUE` | `TRUE` | - | HIGH | `VALID` | NO | Reconciliation: extracted 4 vs reported 4 |
| `public_accounts_reported_count` | `2` | `2` | 1 | HIGH | `VALID` | NO | Reported total publicly written accounts: 2 |
| `public_accounts_extracted_count` | `2` | `2` | - | HIGH | `VALID` | NO | Extracted 2 accounts rendered under 'What is publicly written*' |
| `public_accounts_count_matches` | `TRUE` | `TRUE` | - | HIGH | `VALID` | NO | Reconciliation: extracted 2 vs reported 2 |
| `seven_patterns_reported_count` | `7` | `7` | - | HIGH | `VALID` | NO | Report structure defines exactly 7 standard failure mode patterns ('The Seven'). |
| `seven_patterns_extracted_count` | `7` | `7` | - | HIGH | `VALID` | NO | Extracted 7 failure mode patterns from report text |
| `seven_patterns_count_matches` | `TRUE` | `TRUE` | - | HIGH | `VALID` | NO | Reconciliation: extracted 7 vs reported 7 |
| `safety_performance_inference` | `No conclusive pattern can be drawn from this record. That is a statement about what the public sources say, not a statement that the operation is safe.` | `CANNOT_INFER_SAFE (Absence of regulatory records does not imply safe operation)` | 3 | HIGH | `STANDARDIZED_ASSERTION` | YES | Extracted verbatim from report text: 'No conclusive pattern can be drawn from this record. That is a statement about what the public sources say, not a statement that the operation is safe.' |
| `regulatory_record_status` | `This is the foundation rather than a finding. Nothing has been proven about this organisation — it is where the conversation begins when the public record is silent.` | `Thin Case — No official safety records found` | 2 | HIGH | `STANDARDIZED_ASSERTION` | YES | Extracted verbatim from Page 2 'Thin Case' section: 'This is the foundation rather than a finding. Nothing has been proven about this organisation — it is where the conversation begins when the public record is silent.' |
| `report_audit_status` | `not reviewed` | `not reviewed` | 9 | HIGH | `VALID` | NO | Page 9 footer: 'Status of this copy: not reviewed' |

### 2. Forward Signals (WHAT YOU ARE BUILDING)

| Signal ID | Page | Reported By | Headline | Implication |
| :--- | :---: | :--- | :--- | :--- |
| `SIG-REL-01` | 2 | India | Masterstroke by Mukesh Ambani as Reliance Industries invests Rs 150000000000 in new energy venture, company t | Shown because of what it implies about the work ahead, not as a fact we have proven. |
| `SIG-REL-02` | 2 | Bloomberg | Mukesh Ambani's Reliance (RIL) in Talks for $2 Billion Loan to Fuel Expansion | Shown because of what it implies about the work ahead, not as a fact we have proven. |
| `SIG-REL-03` | 2 | Saur Energy | Reliance To Build Green Energy Giga Complex Spread Across 5,000 Acres in Jamnagar | Shown because of what it implies about the work ahead, not as a fact we have proven. |
| `SIG-REL-04` | 2 | business-standard | Reliance Industries signs MoU to invest Rs 645 cr in Vadhvan port project | Shown because of what it implies about the work ahead, not as a fact we have proven. |

### 3. Publicly Written Accounts

| Account ID | Page | Year | Tag | Outlet | Headline | Snippet |
| :--- | :---: | :---: | :--- | :--- | :--- | :--- |
| `ACC-REL-01` | 7 | - | workers killed | Open source / news | Jamnagar refinery | Jamnagar refinery, also known as RIL Jamnagar or RPL Jamnagar, is a private sector crude oil refinery owned by Reliance ... |
| `ACC-REL-02` | 7 | 2022 | fire | indiantextilemagazine | Reliance to enhance fire retardant and sustainable properties of Recron® FS using Nofia® Technology | your organisation. |

### 4. The Seven Failure Mode Patterns

| Pattern ID | Num | Pattern Name | Company Record Status | Closed By | Benchmark Source | Quote |
| :--- | :---: | :--- | :--- | :--- | :--- | :--- |
| `PAT-REL-01` | 01 | NEVER PRACTISED | `YOUR RECORD IS SILENT` | Genesis + EON Universal | IOGP, Safety Performance Indicators, 2024 data. | "The crew was doing this procedure for the first time, at the equipment." |
| `PAT-REL-02` | 02 | LOST EXPERIENCE | `YOUR RECORD IS SILENT` | EON Tacit |  | "The person who knew how to do it that way retired in March." |
| `PAT-REL-03` | 03 | WHEN THINGS GO WRONG | `YOUR RECORD IS SILENT` | Situation Room + EON Live | International Journal of a share of causes. | "They have only ever practised it going right. Nobody rehearses the bad day." |
| `PAT-REL-04` | 04 | TOLD, NOT TESTED | `YOUR RECORD IS SILENT` | Assess IQ + Competence IQ | International Journal of a share of causes. | "We told them, but we never verified they could actually do it." |
| `PAT-REL-05` | 05 | THE PLAN DIDN'T MATCH THE JOB | `YOUR RECORD IS SILENT` | Permit IQ | International Journal of a share of causes. | "The permit did not cover the entire job, and nobody verified the isolation." |
| `PAT-REL-06` | 06 | NO GUIDANCE IN THE MOMENT | `YOUR RECORD IS SILENT` | Field IQ / Edge | IOGP, Safety Performance Indicators, 2024 data. | "He skipped a step, on the wrong asset, and nobody saw it." |
| `PAT-REL-07` | 07 | THE SAME MISTAKE AGAIN | `YOUR RECORD IS SILENT` | Compound IQ + Distillery | Kimberlite International operator benchmark, 2023. Offshore benchmark. Do not present as an onshore figure. | "It happened before. Nothing changed. So it happened again." |

### 5. Logged Discrepancies & Ambiguities

| Issue ID | Field Name | Type | Description | Report Fragment | Proposed Resolution |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `ISS-REL-01` | `year_founded` | `MISSING_DATA` | Founding year card absent in report | Page 1 contains no 'founded' card. | Preserve as empty; verify if manual corporate data should be populated. |
| `ISS-REL-02` | `people_employed` | `MISSING_DATA` | Headcount disclosure absent in report | No employee count found in cards or filings. | Preserve as empty; do not default to 0. |

---

## ExxonMobil (COMP-XOM)

- **Source File**: `ExxonMobil Pattern Report.pdf`
- **Wingman Tier**: `Tier 1` (`manual_from_trigger_board`)
- **Manual Review Required**: `TRUE`
- **Manual Review Notes**: sec_annual_report_status: DISCREPANCY - Report matched 1 SEC registrant for ExxonMobil but could not read a 10-K/20-F filing. | forward_signals_count: DISCREPANCY - Report build statistics state 6 forward-looking press accounts, but only 4 cards are rendered under 'WHAT YOU ARE BUILDING'. | 12 public press account(s) are unverified by regulator.

### 1. Standardized Field Audit Trail

| Field Name | Report Native Value | Standardized Value | Page | Confidence | Status | Analyst Assigned | Source Evidence |
| :--- | :--- | :--- | :---: | :---: | :---: | :---: | :--- |
| `company_name` | `ExxonMobil` | `ExxonMobil` | 1 | HIGH | `VALID` | NO | Header on Page 1: 'ExxonMobil' |
| `report_window` | `2015–2024` | `2015-2024` | 1 | HIGH | `VALID` | NO | Page 1 card: '2015–2024' Window examined |
| `records_proven` | *[Empty]* | *[Empty]* | - | HIGH | `MISSING_NOT_REPORTED` | NO | Card 'Records proven' not present in report header |
| `official_records_availability` | `None` | `NO_RECORD_REACHABLE` | 1 | HIGH | `CATEGORICAL_UNAVAILABLE` | NO | Page 1 card: 'None Official records reachable' |
| `registry_search_status` | `OSHA, CSB, HSE registries searched` | `SEARCH_EXECUTED` | 8 | HIGH | `VALID` | NO | Page 8 build stats: 'OSHA: 0 inspection(s) found' |
| `official_company_record_found` | `0 confirmed inspection(s) carried citations and became claims` | `FALSE` | 8 | HIGH | `VALID` | NO | Page 8 build stats: '0 confirmed inspection(s) carried citations and became claims' |
| `public_sources_cited` | *[Empty]* | *[Empty]* | - | HIGH | `MISSING_NOT_REPORTED` | NO | Card 'Public sources cited' not present in report header |
| `header_publicly_written_accounts` | `12` | `12` | 1 | HIGH | `VALID` | NO | Page 1 card: '12 Publicly written accounts' |
| `answered_by_record` | *[Empty]* | *[Empty]* | - | HIGH | `MISSING_NOT_REPORTED` | NO | Card 'Answered by your record' not present in report header |
| `header_basis_of_report` | `Open sources` | `Open sources` | 1 | HIGH | `VALID` | NO | Page 1 card: 'Open sources' under 'What this rests on' |
| `headquarters_city` | `Spring` | `Spring` | 1 | HIGH | `VALID` | NO | Page 1 card: 'Spring' above 'head office' |
| `report_geography` | `United States` | `United States` | 2 | HIGH | `VALID` | NO | Page 2 card: 'United States' above 'where they are from' |
| `headquarters_country` | `United States` | `United States` | 2 | HIGH | `VALID` | NO | Page 2 card 'where they are from': 'United States' |
| `operating_countries` | *[Empty]* | *[Empty]* | - | HIGH | `MISSING_NOT_REPORTED` | NO | Operating countries not mentioned in report text |
| `year_founded` | `1882` | `1882` | 1 | HIGH | `VALID` | NO | Page 1 card: '1882' above 'founded' |
| `people_employed` | `74,900` | `74900` | 1 | HIGH | `VALID` | NO | Page 1 card: '74,900 people employed' |
| `line_of_work` | `Oil and gas` | `Oil and gas` | 2 | HIGH | `VALID` | NO | Page 2 card: 'Oil and gas line of work' |
| `citations_count` | `0` | `0` | 3 | HIGH | `EXPLICIT_ZERO` | NO | Page 3 metric card: '0 citations' |
| `penalties_display_text` | `$0` | `$0` | 3 | HIGH | `EXPLICIT_ZERO` | NO | Page 3 metric card: '$0 in penalties' |
| `penalties_amount` | `0` | `0` | 3 | HIGH | `EXPLICIT_ZERO` | NO | Page 3 metric card: '$0' penalty amount |
| `penalties_currency_symbol` | `$` | `$` | 3 | HIGH | `VALID` | NO | Page 3 penalty symbol: '$' |
| `penalties_currency_iso` | `$` | `USD` | 3 | HIGH | `VALID` | YES | Page 3 symbol '$' mapped to ISO 'USD' supported by corporate US context |
| `investigated_accidents_count` | `0` | `0` | 3 | HIGH | `EXPLICIT_ZERO` | NO | Page 3 metric card: '0 investigated accidents' |
| `deaths_count` | `0` | `0` | 3 | HIGH | `EXPLICIT_ZERO` | NO | Page 3 'The shape of the record' card: '0 deaths' |
| `open_information_count` | `6` | `6` | 8 | HIGH | `VALID` | NO | Page 8 build stats: 'Open information: 6 publicly written account(s) found.' |
| `press_reported_account_count` | `6` | `6` | 8 | HIGH | `VALID` | NO | Page 8 build stats: 'Press: 6 reported accounts found.' |
| `forward_looking_press_count` | `6` | `6` | 8 | HIGH | `VALID` | NO | Page 8 build stats: 'Press: 6 accounts of what they are building or hiring for.' |
| `osha_inspections_found` | `0` | `0` | 8 | HIGH | `EXPLICIT_ZERO` | NO | Page 8 build stats: 'OSHA: 0 inspection(s) found' |
| `csb_mentions_found` | `0` | `0` | 8 | HIGH | `EXPLICIT_ZERO` | NO | Page 8 build stats: 'CSB: ... 0 mention this company.' |
| `sec_annual_report_status` | `1 SEC registrant(s) matched 'ExxonMobil', none of them filing an annual report we can read (10-K, 20-F or 40-F)` | `Matched 1 SEC registrant, none filing readable annual report` | 8 | HIGH | `VALID` | YES | Page 8 build stats: '1 SEC registrant(s) matched 'ExxonMobil', none of them filing an annual report we can read (10-K, 20-F or 40-F)' |
| `sec_filing_date` | *[Empty]* | *[Empty]* | - | HIGH | `MISSING_NOT_REPORTED` | NO | No readable 10-K filing date present in report |
| `the_seven_answered_count` | `0` | `0` | 4 | HIGH | `EXPLICIT_ZERO` | NO | Page 4 'The Seven': dynamically computed from 7 individually extracted pattern records: 0 of 7 answered (all 7 state 'YOUR RECORD IS SILENT') |
| `the_seven_overall_status` | `YOUR RECORD IS SILENT` | `YOUR RECORD IS SILENT` | 4 | HIGH | `VALID` | NO | Page 4 'The Seven': confirmed all 7 extracted pattern statuses state 'YOUR RECORD IS SILENT' |
| `forward_signals_reported_count` | `6` | `6` | 8 | HIGH | `VALID` | NO | Report build statistics state: 'Press: 6 accounts of what they are building or hiring for' |
| `forward_signals_extracted_count` | `4` | `4` | - | HIGH | `VALID` | NO | Extracted 4 cards rendered under 'WHAT YOU ARE BUILDING' section |
| `forward_signals_count_matches` | `FALSE` | `FALSE` | - | HIGH | `VALID` | NO | Reconciliation: extracted 4 vs reported 6 |
| `public_accounts_reported_count` | `12` | `12` | 1 | HIGH | `VALID` | NO | Reported total publicly written accounts: 12 |
| `public_accounts_extracted_count` | `12` | `12` | - | HIGH | `VALID` | NO | Extracted 12 accounts rendered under 'What is publicly written*' |
| `public_accounts_count_matches` | `TRUE` | `TRUE` | - | HIGH | `VALID` | NO | Reconciliation: extracted 12 vs reported 12 |
| `seven_patterns_reported_count` | `7` | `7` | - | HIGH | `VALID` | NO | Report structure defines exactly 7 standard failure mode patterns ('The Seven'). |
| `seven_patterns_extracted_count` | `7` | `7` | - | HIGH | `VALID` | NO | Extracted 7 failure mode patterns from report text |
| `seven_patterns_count_matches` | `TRUE` | `TRUE` | - | HIGH | `VALID` | NO | Reconciliation: extracted 7 vs reported 7 |
| `safety_performance_inference` | `No conclusive pattern can be drawn from this record. That is a statement about what the public sources say, not a statement that the operation is safe.` | `CANNOT_INFER_SAFE (Absence of regulatory records does not imply safe operation)` | 3 | HIGH | `STANDARDIZED_ASSERTION` | YES | Extracted verbatim from report text: 'No conclusive pattern can be drawn from this record. That is a statement about what the public sources say, not a statement that the operation is safe.' |
| `regulatory_record_status` | `This is the foundation rather than a finding. Nothing has been proven about this organisation — it is where the conversation begins when the public record is silent.` | `Thin Case — No official safety records found` | 2 | HIGH | `STANDARDIZED_ASSERTION` | YES | Extracted verbatim from Page 2 'Thin Case' section: 'This is the foundation rather than a finding. Nothing has been proven about this organisation — it is where the conversation begins when the public record is silent.' |
| `report_audit_status` | `not reviewed` | `not reviewed` | 9 | HIGH | `VALID` | NO | Page 9 footer: 'Status of this copy: not reviewed' |

### 2. Forward Signals (WHAT YOU ARE BUILDING)

| Signal ID | Page | Reported By | Headline | Implication |
| :--- | :---: | :--- | :--- | :--- |
| `SIG-XOM-01` | 2 | marketscreener | ExxonMobil Ensures Oil Expansion in Angola | Shown because of what it implies about the work ahead, not as a fact we have proven. |
| `SIG-XOM-02` | 2 | Yahoo Finance | ExxonMobil Just Approved an Expansion of a Material Most Investors Have Never Heard Of. Here's Why It Matters. | Shown because of what it implies about the work ahead, not as a fact we have proven. |
| `SIG-XOM-03` | 2 | BIC Magazine | ExxonMobil invests in Louisiana's next generation of fire service leaders | Shown because of what it implies about the work ahead, not as a fact we have proven. |
| `SIG-XOM-04` | 2 | Carbon Herald | ExxonMobil Eyes Texas Expansion With New Carbon Storage Project | Shown because of what it implies about the work ahead, not as a fact we have proven. |

### 3. Publicly Written Accounts

| Account ID | Page | Year | Tag | Outlet | Headline | Snippet |
| :--- | :---: | :---: | :--- | :--- | :--- | :--- |
| `ACC-XOM-01` | 6 | - | explosion or fire | Open source / news | ExxonMobil Beaumont Refinery | The ExxonMobil Refinery in Beaumont, Texas was built along the banks of the Neches River in 1903. The refinery is curren... |
| `ACC-XOM-02` | 6 | - | explosion or fire | Open source / news | Baytown Refinery | ExxonMobil's Baytown Refinery is a major oil refinery named after and located in Baytown, Texas. It has capacity of 588,... |
| `ACC-XOM-03` | 6 | 1999 | explosion or fire | Open source / news | ExxonMobil Australia | (LIP) in Hastings. ExxonMobil Australia operates retail petrol operations under the Mobil brand. Prior to the merger of ... |
| `ACC-XOM-04` | 6 | 2024 | explosion or fire | Open source / news | List of oil refineries | 2024-11-14. "ExxonMobil boosts fuel supply with $2 billion Beaumont refinery expansion". Corporate.exxonmobil.com. 16 Ma... |
| `ACC-XOM-05` | 6 | 1998 | workers killed | Open source / news | 1998 Esso Longford fire | subsidiary of US-based company Exxon, which has since merged with Mobil, becoming ExxonMobil. Built in 1969, the plant a... |
| `ACC-XOM-06` | 6 | - | workers killed | Open source / news | List of pipeline accidents in the United States in the 1990s | pipelines are re-purposed to carry different products. January 2 – An ExxonMobil underwater pipeline, located at the mou... |
| `ACC-XOM-07` | 7 | 2026 | fire | Reuters | ExxonMobil temporarily halts operations at Guyana site after fire, Bloomberg News reports |  |
| `ACC-XOM-08` | 7 | 2026 | leaks | HazardEx | ExxonMobil fined £267,000 after five flammable hydrocarbon leaks at Fife, UK plant | organisation. |
| `ACC-XOM-09` | 7 | 2026 | leaks | BBC | ExxonMobil fined £267,000 over chemical leaks at Mossmorran |  |
| `ACC-XOM-10` | 7 | 2026 | fire | BIC Magazine | ExxonMobil invests in Louisiana's next generation of fire service leaders | organisation. |
| `ACC-XOM-11` | 7 | 2026 | fire | Demerara Waves Online News- Guyana | ExxonMobil confirms "small fire" forced suspension of Liza Unity FPSO operations | a fact about your organisation. |
| `ACC-XOM-12` | 7 | 2026 | fire | The Edge Malaysia | ExxonMobil suspends Guyana Liza Unity operation after small fire | organisation. |

### 4. The Seven Failure Mode Patterns

| Pattern ID | Num | Pattern Name | Company Record Status | Closed By | Benchmark Source | Quote |
| :--- | :---: | :--- | :--- | :--- | :--- | :--- |
| `PAT-XOM-01` | 01 | NEVER PRACTISED | `YOUR RECORD IS SILENT` | Genesis + EON Universal | IOGP, Safety Performance Indicators, 2024 data. | "The crew was doing this procedure for the first time, at the equipment." |
| `PAT-XOM-02` | 02 | LOST EXPERIENCE | `YOUR RECORD IS SILENT` | EON Tacit |  | "The person who knew how to do it that way retired in March." |
| `PAT-XOM-03` | 03 | WHEN THINGS GO WRONG | `YOUR RECORD IS SILENT` | Situation Room + EON Live | International Journal of share of causes. | "They have only ever practised it going right. Nobody rehearses the bad day." |
| `PAT-XOM-04` | 04 | TOLD, NOT TESTED | `YOUR RECORD IS SILENT` | Assess IQ + Competence IQ | International Journal of share of causes. | "We told them, but we never verified they could actually do it." |
| `PAT-XOM-05` | 05 | THE PLAN DIDN'T MATCH THE JOB | `YOUR RECORD IS SILENT` | Permit IQ | International Journal of share of causes. | "The permit did not cover the entire job, and nobody verified the isolation." |
| `PAT-XOM-06` | 06 | NO GUIDANCE IN THE MOMENT | `YOUR RECORD IS SILENT` | Field IQ / Edge | IOGP, Safety Performance Indicators, 2024 data. | "He skipped a step, on the wrong asset, and nobody saw it." |
| `PAT-XOM-07` | 07 | THE SAME MISTAKE AGAIN | `YOUR RECORD IS SILENT` | Compound IQ + Distillery | Kimberlite International Oilfield benchmark, 2023. Offshore benchmark. Do not present as an onshore figure. | "It happened before. Nothing changed. So it happened again." |

### 5. Logged Discrepancies & Ambiguities

| Issue ID | Field Name | Type | Description | Report Fragment | Proposed Resolution |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `ISS-XOM-01` | `sec_annual_report_status` | `DISCREPANCY` | Report matched 1 SEC registrant for ExxonMobil but could not read a 10-K/20-F filing. | Page 8: '1 SEC registrant(s) matched 'ExxonMobil', none of them filing an annual report we can read (10-K, 20-F or 40-F)' | Retain native match note; flag for analyst review. |
| `ISS-XOM-02` | `forward_signals_count` | `DISCREPANCY` | Report build statistics state 6 forward-looking press accounts, but only 4 cards are rendered under 'WHAT YOU ARE BUILDING'. | Page 2 has 4 cards; Page 8/10 states 'Press: 6 accounts of what they are building or hiring for.' | Preserve 4 extracted signals; flag 2 unaccounted background signals for analyst verification. |

---

