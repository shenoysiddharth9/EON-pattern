"""
Data models for the EON Pattern Report extractor.
Includes stable identifiers, metadata propagation across all tables,
and strict distinction between native and standardized values.
"""
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any

PARSER_VERSION = "1.1.0"


@dataclass
class WingmanInfo:
    """Manual classification metadata from Trigger Board."""
    tier: str  # e.g., "Tier 1", "Tier 2", "Tier 3"
    source: str = "manual_from_trigger_board"


@dataclass
class FieldEvidence:
    """Granular audit trail for an extracted field."""
    company_id: str
    company_name: str
    source_pdf_filename: str
    parser_version: str
    extraction_timestamp: str
    field_name: str
    report_native_value: Optional[str]
    standardized_value: Optional[str]
    source_evidence: str
    page_number: Optional[int]
    confidence: str  # "HIGH", "MEDIUM", "LOW"
    validation_status: str  # "VALID", "EXPLICIT_ZERO", "MISSING_NOT_REPORTED", "CATEGORICAL_UNAVAILABLE", "STANDARDIZED_ASSERTION", "PARSING_FAILED", "DERIVED_RECONCILIATION", "AMBIGUOUS"
    is_analyst_assigned: bool = False
    source_type: Optional[str] = None
    source_date: Optional[str] = None
    value_context: Optional[str] = None
    profile_card_present: Optional[bool] = None
    derivation_method: Optional[str] = None
    derivation_components: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        p_card_str = ""
        if self.profile_card_present is True:
            p_card_str = "TRUE"
        elif self.profile_card_present is False:
            p_card_str = "FALSE"

        return {
            "parser_version": self.parser_version,
            "extraction_timestamp": self.extraction_timestamp,
            "source_pdf_filename": self.source_pdf_filename,
            "company_id": self.company_id,
            "company_name": self.company_name,
            "field_name": self.field_name,
            "report_native_value": self.report_native_value if self.report_native_value is not None else "",
            "standardized_value": self.standardized_value if self.standardized_value is not None else "",
            "source_evidence": self.source_evidence,
            "page_number": self.page_number if self.page_number is not None else "",
            "confidence": self.confidence,
            "validation_status": self.validation_status,
            "is_analyst_assigned": "TRUE" if self.is_analyst_assigned else "FALSE",
            "source_type": self.source_type if self.source_type is not None else "",
            "source_date": self.source_date if self.source_date is not None else "",
            "value_context": self.value_context if self.value_context is not None else "",
            "profile_card_present": p_card_str,
            "derivation_method": self.derivation_method if self.derivation_method is not None else "",
            "derivation_components": self.derivation_components if self.derivation_components is not None else "",
        }


@dataclass
class ForwardSignal:
    """One press signal or 'WHAT YOU ARE BUILDING' forward item."""
    parser_version: str
    extraction_timestamp: str
    source_pdf_filename: str
    company_id: str
    company_name: str
    signal_id: str
    signal_index: int
    headline: str
    reported_by: str
    implication_text: str
    page_number: int
    source_category: str = "WHAT YOU ARE BUILDING"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "parser_version": self.parser_version,
            "extraction_timestamp": self.extraction_timestamp,
            "source_pdf_filename": self.source_pdf_filename,
            "company_id": self.company_id,
            "company_name": self.company_name,
            "signal_id": self.signal_id,
            "signal_index": self.signal_index,
            "headline": self.headline,
            "reported_by": self.reported_by,
            "implication_text": self.implication_text,
            "page_number": self.page_number,
            "source_category": self.source_category,
        }


@dataclass
class PublicAccount:
    """One publicly written account from 'What is publicly written*'."""
    parser_version: str
    extraction_timestamp: str
    source_pdf_filename: str
    company_id: str
    company_name: str
    account_id: str
    account_index: int
    year: Optional[str]
    tag: Optional[str]
    headline: str
    source_outlet: str
    description_snippet: str
    page_number: int
    official_status: str = "Not verified, and not treated as a fact about your organisation"
    raw_evidence: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "parser_version": self.parser_version,
            "extraction_timestamp": self.extraction_timestamp,
            "source_pdf_filename": self.source_pdf_filename,
            "company_id": self.company_id,
            "company_name": self.company_name,
            "account_id": self.account_id,
            "account_index": self.account_index,
            "year": self.year if self.year else "",
            "tag": self.tag if self.tag else "",
            "headline": self.headline,
            "source_outlet": self.source_outlet,
            "description_snippet": self.description_snippet,
            "page_number": self.page_number,
            "official_status": self.official_status,
            "raw_evidence": self.raw_evidence,
        }


@dataclass
class SevenPattern:
    """One of the Seven failure mode patterns."""
    parser_version: str
    extraction_timestamp: str
    source_pdf_filename: str
    company_id: str
    company_name: str
    pattern_id: str
    pattern_number: str  # "01" through "07"
    pattern_name: str
    quote: str
    company_record_status: str  # e.g., "YOUR RECORD IS SILENT"
    solution_closed_by: str
    sector_benchmark_summary: str
    sector_benchmark_source: str
    page_number: int
    sector_benchmark_qualifier: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "parser_version": self.parser_version,
            "extraction_timestamp": self.extraction_timestamp,
            "source_pdf_filename": self.source_pdf_filename,
            "company_id": self.company_id,
            "company_name": self.company_name,
            "pattern_id": self.pattern_id,
            "pattern_number": self.pattern_number,
            "pattern_name": self.pattern_name,
            "quote": self.quote,
            "company_record_status": self.company_record_status,
            "solution_closed_by": self.solution_closed_by,
            "sector_benchmark_summary": self.sector_benchmark_summary,
            "sector_benchmark_source": self.sector_benchmark_source,
            "sector_benchmark_qualifier": self.sector_benchmark_qualifier,
            "page_number": self.page_number,
        }


@dataclass
class ValidationIssue:
    """Tracked issue, ambiguity, discrepancy, or parsing failure."""
    parser_version: str
    extraction_timestamp: str
    source_pdf_filename: str
    company_id: str
    company_name: str
    issue_id: str
    field_name: str
    issue_type: str  # "AMBIGUITY", "MISSING_DATA", "DISCREPANCY", "REVIEW_REQUIRED", "PARSING_FAILED"
    description: str
    report_native_fragment: str
    page_number: Optional[int]
    resolution_proposed: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "parser_version": self.parser_version,
            "extraction_timestamp": self.extraction_timestamp,
            "source_pdf_filename": self.source_pdf_filename,
            "company_id": self.company_id,
            "company_name": self.company_name,
            "issue_id": self.issue_id,
            "field_name": self.field_name,
            "issue_type": self.issue_type,
            "description": self.description,
            "report_native_fragment": self.report_native_fragment,
            "page_number": self.page_number if self.page_number is not None else "",
            "resolution_proposed": self.resolution_proposed,
        }


@dataclass
class CompanyRecord:
    """Complete company extraction container."""
    company_id: str
    company_name: str
    source_pdf_filename: str
    wingman: WingmanInfo
    metadata: Dict[str, Any] = field(default_factory=dict)
    fields: Dict[str, FieldEvidence] = field(default_factory=dict)
    forward_signals: List[ForwardSignal] = field(default_factory=list)
    public_accounts: List[PublicAccount] = field(default_factory=list)
    seven_patterns: List[SevenPattern] = field(default_factory=list)
    validation_issues: List[ValidationIssue] = field(default_factory=list)

    def get_standardized(self, field_name: str) -> Optional[str]:
        fe = self.fields.get(field_name)
        return fe.standardized_value if fe else None

    def get_native(self, field_name: str) -> Optional[str]:
        fe = self.fields.get(field_name)
        return fe.report_native_value if fe else None
