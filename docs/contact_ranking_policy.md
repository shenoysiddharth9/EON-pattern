# Contact Selection Ranking Policy & Weak-Match Adjudication

**Status**: Active Production Standard (Phase 3.1: Aggregator Reclassification, Freshness Distinction & Disconfirmation Retrieval)  
**Applicability**: EON Commercial Intelligence (`dashboard/contact_research.py`, `dashboard/pages/11_company_browser.py`, `dashboard/pages/13_contact_research.py`, `contact_intelligence/eon_contact_research_server_purdue_v1.py`, `contact_intelligence/eon_contact_research_server_agentic_v1.py`)  
**Verified Production Baseline**: Commits `e851d21`, `4afba92`, `0174d25`, `2ea2484`, `9cd8221`, `156c8b5`, `4ebde39`, `3de6915`  

---

## 1. Executive Summary & Design Invariant

The Contact Intelligence engine identifies and ranks enterprise training decision-makers for industrial and enterprise accounts.

### Core Invariant
> **Frontline SDR Protection Rule**: A low-confidence fallback or operational practitioner lead must **never** be presented as a verified enterprise budget holder or primary resolved contact.
>
> If only fallback/practitioner leads or uncorroborated LinkedIn profiles exist, the top-level outcome **must** resolve to:
> $$\text{contact\_research\_status} = \text{"Role Found — Person Unresolved"}$$
> Weak candidates are preserved **strictly** inside a collapsed SDR discovery expander with explicit practitioner warnings.

---

## 2. Title Classification Hierarchy

Every candidate job title is classified via `classify_title_tier(title)` into one of five structured tiers. Precedence rules ensure practitioner compounds (e.g., *"Training Program Manager"*) are never misclassified as management roles:

| Tier Identifier | Base Score | Target Roles / Keywords | Adjudication Behavior |
| :--- | :---: | :--- | :--- |
| **`strong_leadership`** | **100** | Chief Learning Officer (CLO), VP of Training, Director of Training, Head of Training, Head of Learning & Development, VP of Workforce Development | **Primary Target**. Eligible for `Verified Contact Found` with corporate domain or multi-source evidence. |
| **`specialized_leadership`** | **80** | Director/Head of Technical Training, Operations Training, Safety Training, Operational Capability | **Secondary Target**. High relevance for asset-heavy operators. |
| **`ambiguous_leadership`** | **65** | Training Manager, Learning Manager, Technical Training Lead | **Ambiguous**. Requires first-party corporate domain corroboration. Demoted by **-25 penalty** if evidence is LinkedIn-only or third-party only. |
| **`practitioner`** | **20** | Training Program Manager, Project Training Manager, Training Coordinator, Specialist, Instructor, Curriculum Designer | **Operational / Practitioner**. Automatically flagged as `is_weak_match = True`. Demoted below leadership roles and moved to expander. |
| **`fallback`** | **10** | Non-training executive (e.g., Chief People Officer, HR Director, General Manager) or unverified legacy role | **Fallback Match**. Automatically flagged as `is_weak_match = True`. Never presented as primary resolved contact. |

---

## 3. Canonical Evidence Layer & Source Independence (Phase 2 Baseline)

### 3.1 URL Canonicalization Specification
To ensure evidence scoring evaluates truly independent sources rather than cosmetic URL permutations or tracking variants, every ingested URL undergoes deterministic canonicalization via `canonicalize_url(url)`:
1. **Protocol Normalization**: Unifies `http://` and scheme-less strings to `https://`.
2. **Host Normalization**: Lowercases hostname, removes default ports (`:80`, `:443`), and strips redundant `www.` prefixes.
3. **Path Normalization**: Strips trailing slashes from resource paths (preserving root `/`), collapses multi-slash sequences.
4. **Fragment Removal**: Discards all URL fragments (`#experience`, `#about`).
5. **Tracking & Session Parameter Stripping**: Strips tracking parameters including:
   - Campaign analytics: `utm_source`, `utm_medium`, `utm_campaign`, `utm_term`, `utm_content`, `utm_name`
   - Platform click identifiers: `fbclid`, `gclid`, `gclsrc`, `dclid`, `msclkid`, `twclid`, `igshid`, `mc_eid`
   - Professional network tracking: `ref`, `trk`, `trackingId`, `refId`, `originalSubdomain`, `miniProfileUrn`, `context`, `session_id`, `sid`, `_hsenc`, `_hsmi`, `source`, `v`, `t`
6. **Deterministic Query Ordering**: Any remaining functional parameters are sorted lexicographically by key and value.

### 3.2 Raw URL Auditability & Zero-Discard Policy
- **Auditability Preservation**: Every collected raw URL is retained untouched in audit records.
- **Explicit Classification**: Raw URLs are mapped 1:1 to their canonical form and assigned a provenance status:
  - `Primary Canonical`: The first evaluated canonical instance of an independent evidence family.
  - `Duplicate URL`: An identical canonical URL encountered across multiple queries or snippets.
  - `Family Mirror`: A distinct canonical URL belonging to an already represented aggregator/mirror family.
- **No Silent Discards**: Evidence is never silently dropped; excluded records are retained and transparently surfaced in the evidence audit expander.

### 3.3 Source Families & Authority Hierarchy
Ingested evidence domains are mapped into explicit source families and authority tiers:

| Source Family | Authority Tier | Description & Representative Domains | Corroboration Role |
| :--- | :--- | :--- | :--- |
| **`corporate`** | `tier_1_first_party` | First-party corporate websites, leadership pages, press releases matching company domain/name. | **Gold Standard**. Outranks third-party profiles; qualifies leadership for `Verified`. |
| **`regulatory`** | `tier_2_verified_institutional` | SEC EDGAR, Companies House, official corporate registries, government filings (`sec.gov`, `gov.uk`). | **Institutional Corroboration**. Provides definitive enterprise entity validation. |
| **`editorial`** | `tier_2_verified_institutional` | Major business press, verified trade journals, and industrial publications (`reuters.com`, `bloomberg.com`, `wsj.com`, `rigzone.com`, `offshore-energy.biz`, `industryweek.com`). | **Substantive Corroboration**. Validates executive appointments and initiatives. |
| **`conference`** | `tier_2_verified_institutional` | Industry summits, technical conferences, verified speaker rosters (`spe.org`, `adipec.com`, `otcnet.org`, `td.org`, `chieflearningofficer.com`). | **Operational Corroboration**. Confirms active speaking or practitioner role. |
| **`linkedin_ecosystem`** | `tier_3_professional_ecosystem` | LinkedIn profiles (`linkedin.com`) plus known profile directories and scraper mirrors: `zoominfo.com`, `zi.com`, `rocketreach.co`, `rocketreach.com`, `apollo.io`, `lusha.com`, `signalhire.com`, `contactout.com`, `clay.com`, `clay.run`, `topionetworks.com`, `leadiq.com`, `datanyze.com`, `cognism.com`, `theorg.com`, `adapt.io`, `updata.com`, `swordfish.ai`, `kaspr.io`. | **Aggregator Ecosystem**. All domains in this family collapse into **one** source. Cannot trigger multi-source bonus or `Verified` status alone. |
| **`directory_unclassified`** | `tier_4_unverified_web` | Third-party company directories, crowdsourced compensation aggregators (`comparably.com`), blogs, or unclassified repositories. | **Conservative Default**. Aggregators and unknown directories default to unclassified and **never** provide independent corroboration against LinkedIn. |

### 3.4 Independence Rules & Transparent Summary
1. **Intra-Family Collapse**: Multiple URLs within the same source family count as **one** source family.
2. **Multi-Source Corroboration Requirement**: A candidate requires $\ge 2$ substantively independent source families (e.g. `corporate` + `linkedin_ecosystem`, `corporate` + `conference`, or `editorial` + `regulatory`).
3. **LinkedIn-Only Constraint**: Profiles supported solely by the `linkedin_ecosystem` (regardless of how many scraper mirrors like Apollo, RocketReach, or ZoomInfo are present) or unclassified directories have exactly **1 independent source family**. They receive the LinkedIn-only penalty and are strictly capped:
   - `evidence_confidence`: capped at **`Low`**
   - `current_employment_status`: capped at **`Probable`** (cannot be `Verified`)
4. **Transparent Audit String**: Every candidate card and audit panel surfaces:
   $$\text{“X independent sources · Y raw URLs · Z duplicates/mirrors excluded”}$$

### 3.5 Scoring Formula (`score_candidate`)
- Base Tier Score: `strong_leadership` (100), `specialized_leadership` (80), `ambiguous_leadership` (65), `tertiary_leadership` (50), `practitioner` (20), `fallback` (10).
- Corroboration Adjustments:
  - First-party corporate evidence (`has_corporate == True`): **+40 bonus**
  - Multi-source independent corroboration (`num_independent_sources >= 2`): **+20 bonus**
  - LinkedIn-only / mirror-only evidence (`is_linkedin_only == True`): **-15 penalty**
  - Ambiguous leadership title lacking corporate proof: **-25 penalty**

---

## 4. Employment Freshness and Current-Employment Verification (Phase 3 & Phase 3.1 Baseline)

### 4.1 Separation of Freshness from Title Seniority
Employment freshness is assessed through an independent evaluation layer strictly decoupled from title strength, role seniority, and source quantity. A historically senior contact (e.g., an EVP or VP from an archived report) must **never** outrank a clearly active, current contact (e.g., a Director on the live corporate roster) solely due to historical title prestige.

### 4.2 Explicit Employment-Freshness States
Every evaluated candidate is assigned one of four deterministic freshness states:
1. **`Current Employment Confirmed`**: Verified active tenure through a live first-party organizational roster on the company domain, or an official corporate/regulatory filing within the active 12-month window.
2. **`Current Employment Likely`**: High probability of active tenure through recent corporate filings (12–24 months), dated editorial/institutional publication ($\le 18$ months), or active professional profile ($\le 12$ months).
3. **`Employment Unconfirmed` (Insufficient Evidence for Current Tenure)**: Evidence supporting target-company employment is undated, aggregator-only, uncorroborated profile-only, or moderately aging (24–36 months for corporate; 18–30 months for editorial/profile). There is **no affirmative proof of departure or competing employment**; rather, there is simply **insufficient authority or recency** to confirm current active tenure. Candidates in this state are ineligible to serve as default primary contacts.
4. **`Possible Former Employee / Stale Evidence` (Positively Contradicted or Definitively Historic)**: Candidate is either (a) positively contradicted by credible newer evidence indicating departure or transition to a different employer, or (b) supported only by definitively historical documents exceeding maximum retention limits (>36 months for corporate; >30 months for editorial/profiles). Candidates in this state are actively suppressed to the weak/stale section.

### 4.3 Five-Tier Evidence Hierarchy for Freshness
| Freshness Tier | Authority Classification | Evidence Types & Representative Sources | Maximum Freshness State |
| :--- | :--- | :--- | :--- |
| **Tier 1** | `tier_1_corporate_first_party` | Active first-party corporate leadership/team rosters (`/leadership`, `/executive-team`, `/about-us`), official company bios, dated press releases. | **`Current Employment Confirmed`** |
| **Tier 2** | `tier_1_regulatory_filing` | Official statutory filings, SEC EDGAR 10-K/Proxy statements with explicit filing dates. | **`Current Employment Confirmed`** ($\le 12$m) |
| **Tier 3** | `tier_2_verified_institutional` | Reputable dated trade journals, industrial editorial press. | **`Current Employment Likely`** ($\le 18$m) |
| **Tier 4** | `tier_4_unverified_web` / `linkedin_ecosystem` | Professional profile networks (LinkedIn personal profiles, posts). | **`Current Employment Likely`** ($\le 12$m; **never** `Confirmed`) |
| **Tier 5** | `tier_4_unverified_web` / `directory_unclassified` | Aggregators, scrapers, data brokers (Comparably, ZoomInfo, RocketReach, Apollo, etc.). | **`Employment Unconfirmed`** (**never** `Confirmed` or `Likely`) |

### 4.4 Validated Threshold Windows
- **Corporate & Regulatory (Tiers 1 & 2)**:
  - Live organizational roster page (undated or dated): `Current Employment Confirmed`
  - Dated document $\le 12$ months: `Current Employment Confirmed`
  - Dated document $> 12$ and $\le 24$ months: `Current Employment Likely`
  - Dated document $> 24$ and $\le 36$ months: `Employment Unconfirmed`
  - Dated document $> 36$ months: `Possible Former Employee / Stale Evidence`
- **Reputable Editorial & Institutional (Tier 3)**:
  - Dated article $\le 18$ months: `Current Employment Likely`
  - Dated article $> 18$ and $\le 30$ months: `Employment Unconfirmed`
  - Dated article $> 30$ months: `Possible Former Employee / Stale Evidence`
- **Professional Profiles (Tier 4 / LinkedIn)**:
  - **Hard Invariant**: LinkedIn/profile-based evidence **cannot by itself** create `Current Employment Confirmed`.
  - Active / Dated $\le 12$ months: `Current Employment Likely`
  - Undated or $> 12$ months: `Employment Unconfirmed`
  - Dated $> 30$ months: `Possible Former Employee / Stale Evidence`
- **Aggregators & Directories (Tier 5 / Comparably)**:
  - **Hard Invariant**: An undated third-party aggregator/directory listing can **never** produce `Current Employment Confirmed` or `Current Employment Likely`. Maximum freshness state is strictly **`Employment Unconfirmed`**.
  - Aggregator evidence may be preserved for discovery and audit trail, but **cannot** make a candidate eligible as default primary contact.

### 4.5 Contradiction & Departure Handling
If any evidence snippet, profile, or publication indicates departure or a transition:
- Current employment status is **immediately suppressed** to `Former`.
- Freshness state is forced to **`Possible Former Employee / Stale Evidence`**.
- Candidate is barred from serving as default primary contact and retained only in the collapsed weak/stale section.

**Distinction from Insufficient Evidence**:
- `Possible Former Employee / Stale Evidence` strictly requires **positive, affirmative evidence of departure** (e.g., "left [company]", "formerly at [company]") or transition to a competing employer ("now at [other company]", "joined [other company]"), or definitively expired historical corporate records (>36 months).
- By contrast, `Employment Unconfirmed` reflects an **absence of sufficient corroboration** or reliance on undated aggregator-only evidence, rather than affirmative proof of departure.

### 4.6 Seniority-Decoupled Ranking Modifiers
In `score_candidate`, freshness modifies candidate score to ensure active employment dominates historic seniority:
- `Current Employment Confirmed`: **+30 bonus**
- `Current Employment Likely`: **+10 bonus**
- `Employment Unconfirmed`: **-20 penalty**
- `Possible Former Employee / Stale Evidence`: **-60 penalty**

*Example*: Historic VP from 2021 PDF (Base 100 + Corp 40 - Stale 60 = 80) is defeated by Current Director on live roster (Base 80 + Corp 40 + Confirmed 30 = 150).

### 4.7 Stale / Unconfirmed Default Contact Protection
- A candidate classified as `Possible Former Employee / Stale Evidence` or `Employment Unconfirmed` **cannot** be rendered as the normal default recommended primary contact.
- If only undated aggregator evidence supports the candidate for the target company:
  - Freshness state resolves to **`Employment Unconfirmed`** (insufficient evidence for current tenure).
  - The candidate is **suppressed from default primary recommendation** and retained only under Best Available Weak Matches.
  - The top-level account outcome resolves to `Role Found — Person Unresolved` with an explicit Stale Evidence Warning.

#### 4.7.1 Analytical Distinction: Insufficient Evidence vs. Positively Contradicted Former Employee
To maintain analytical precision and avoid ungrounded assertions, the adjudication engine strictly separates:
1. **`Employment Unconfirmed` (Insufficient Evidence for Current Tenure)**:
   - **Condition**: Available records are undated aggregators (e.g. Comparably), scrapers, or uncorroborated third-party directories.
   - **Semantics**: The engine lacks verified proof that the person currently holds the target role. It does **not** assert or imply that the candidate has departed or works elsewhere.
   - **Adjudication**: Candidate is disqualified from primary recommendation solely due to lack of verifiable proof; preserved only in the collapsed weak matches expander.
2. **`Possible Former Employee / Stale Evidence` (Positively Contradicted / Historical Expiration)**:
   - **Condition**: Specific retrieved evidence establishes an affirmative departure or appointment to another firm, or dated corporate records exceed 36 months.
   - **Semantics**: The engine possesses affirmative proof indicating the candidate is no longer in the role.
   - **Adjudication**: Suppressed with an explicit departure/transition rationale.

#### 4.7.2 Benchmark Adjudication Note: Baker Hughes (Jose Fernandez)
- **Precise Status**: Jose Fernandez is assigned **`Employment Unconfirmed`** (Confidence: `Low`), **not** `Possible Former Employee`.
- **Suppression Mechanism**: He is suppressed from being Baker Hughes' default recommended contact because the available evidence is **insufficient and aggregator-only** (`comparably.com`), which is capped at `Employment Unconfirmed` under Section 4.4 and Section 4.7.
- **Strict Factual Guard**: The system does **not** claim or imply that Jose Fernandez is confirmed as a former Baker Hughes employee unless a credible retrieved source explicitly proves he moved elsewhere (e.g., explicit departure or verified transition to Novartis or another employer).
- **Adjudication Invariant**: In the absence of an affirmative cross-employer transition snippet retrieved and retained during research, he is excluded from default primary recommendation strictly under the **insufficient-evidence invariant** (undated aggregator evidence cannot establish current tenure), not under an unsubstantiated former-employee presumption.

### 4.8 Candidate Disconfirmation Retrieval (Phase 3.1 Corrective Addendum)
Once a primary candidate is identified, the research engine performs a bounded disconfirmation check (at most 2 queries):
1. **Career-Transition Query**:
   `"{candidate_name}" "{company_name}" (left OR former OR formerly OR joined OR appointed OR "now at" OR "current role")`
2. **Current-Employer Discovery Query**:
   `"{candidate_name}" ("current role" OR "currently" OR joined OR appointed OR "now at")`

**Contradiction Association Rules**:
- Contradiction statements must be tied to the candidate's identity (e.g. name appears within the same clause/sentence).
- Transition statements (`joined [company]`, `now at [company]`, `currently [role] at [company]`) trigger contradiction only when the competing company is distinct from the target company.
- Unrelated third-party transitions (e.g., someone else joining another firm) are prevented from causing false positives.

---

## 5. Top-Level Status & UI Presentation Rules

### 5.1 When to Set `"Role Found — Person Unresolved"`
The top-level outcome resolves to `"Role Found — Person Unresolved"` whenever:
1. `primary_contact` title is classified as `practitioner` or `icp_level == "Fallback"`.
2. `primary_contact` has `is_linkedin_only == True` and `evidence_confidence == "Low"`.
3. `primary_contact` title is `ambiguous_leadership` without first-party corporate domain corroboration.
4. `primary_contact` is not in `{"strong_leadership", "specialized_leadership"}` and lacks corporate domain proof.

When this condition is triggered:
- `is_weak_match = True`
- `ideal_role_person_unresolved = True`
- `contact_research_status = "Role Found - Person Unresolved"`
- `primary_contact["match_quality"] = "Best Available Weak Match"`
- `primary_contact["is_weak_match"] = True`
- All candidates are placed in `weak_matches`

### 5.2 UI Presentation Contract
1. **Primary Result Card**:
   - Status badge: `Role Found — Person Unresolved` (amber `#f59e0b`)
   - Header callout:
     ```html
     <div style="background:#fffbeb; border:1px solid #fde68a; border-radius:6px; padding:12px; margin-bottom:14px;">
       <p style="margin:0; font-size:13px; color:#92400e;">
         ⚠️ <strong>Enterprise Leadership Unresolved</strong>: No verified enterprise training leader (Director/Head/VP) was resolved in indexed records. The best available weak match is retained below under Best Available Weak Matches.
       </p>
     </div>
     ```
   - Target Role display: `🎯 Ideal / Target Role: Head of Training / Training Director`
   - Decision reason explains why leadership is unresolved and that weak match is preserved for discovery.
   - **No candidate card is displayed above the fold.**

2. **Weak Matches Expander (`st.expander`)**:
   - Label: `🔍 Show Best Available Weak Matches (N)`
   - Default state: **Collapsed** (`expanded=False`)
   - Warning banner at the top of the expander:
     > ⚠️ **Operational / Practitioner Role Warning**: These contacts hold operational or practitioner roles (e.g., Program Manager, Training Coordinator, Specialist) or lack first-party corporate corroboration. They are **NOT** verified enterprise training budget holders.
   - Each weak candidate card features:
     - Badge: `🏷️ Best Available Weak Match`
     - Role Type: `Fallback / Training Practitioner`
     - ICP Level, Confidence, Employment labels
     - Secure, sanitized source links (`target="_blank"` and `rel="noopener noreferrer"`)

---

## 6. Architectural Parity Across Entry Points

All entry points adhere to identical scoring, classification, and normalization invariants:

```
[UI Invocations]
├── Company Browser (dashboard/pages/11_company_browser.py)
│    └── execute_contact_research() ──> render_contact_card()
└── Contact Research (dashboard/pages/13_contact_research.py)
     └── render_contact_research_ui() ──> execute_contact_research() ──> render_contact_card()

[Adjudication & Normalization Backends]
├── dashboard/contact_research.py (In-process engine & normalizer)
├── contact_intelligence/eon_contact_research_server_purdue_v1.py (Purdue GenAI backend)
└── contact_intelligence/eon_contact_research_server_agentic_v1.py (OpenAI fallback backend)
```

Both backends share:
- Identical `SCRAPER_DOMAINS` set
- Identical `classify_title_tier(title)` implementation
- Identical `evaluate_candidate_corroboration()` logic
- Identical `evaluate_employment_freshness()` logic
- Identical `score_candidate()` ranking formula
- Identical `adjudicate_contact_research()` decision rules

---

## 7. Regression & Smoke Verification Suite

The policy is tested via `tests/test_contact_research_smoke.py`:
- `test_regression_linkedin_plus_rocketreach_not_corroboration`: Proves scrapers do not increment credible sources.
- `test_regression_corporate_domain_outranks_linkedin_only`: Proves corporate lead outranks LinkedIn-only candidate.
- `test_regression_training_manager_ambiguous_without_first_party_evidence`: Proves ambiguous titles without corporate proof are penalised.
- `test_regression_saipem_weak_match_defaults_to_role_found_person_unresolved`: Proves Saipem defaults to unresolved status.
- `test_regression_weak_match_expander_ui_rendering`: Verifies expander and warning banner UI rendering.
- `test_regression_weak_match_parity_across_all_entry_points`: Confirms identical behavior across all four code entry points.
- `test_regression_strong_positive_benchmark_not_suppressed`: Proves verified corporate leadership benchmark is never mistakenly suppressed or collapsed.
- `test_phase3_1_comparably_only_undated_cannot_be_primary`: Verifies Comparably-only listings cap at Employment Unconfirmed and cannot be primary.
- `test_phase3_1_baker_hughes_jose_fernandez_outcomes`: Verifies Baker Hughes / Jose Fernandez resolves to Role Found — Person Unresolved under aggregator-only evidence.
- `test_phase3_1_saipem_remains_unresolved_weak_leads_non_primary`: Verifies Saipem remains unresolved with weak leads non-primary.
