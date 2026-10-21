"""
PDF loading and unicode text normalization.
"""
from dataclasses import dataclass
from pathlib import Path
from typing import List
import unicodedata
import pypdf


@dataclass
class PageData:
    page_number: int
    raw_text: str
    normalized_text: str


def normalize_pdf_text(text: str) -> str:
    """
    Normalize PDF text:
    - NFKD normalization decomposes ligatures (e.g. 'ﬁ' -> 'fi', 'ﬂ' -> 'fl')
    - Standardize whitespace, non-breaking spaces, and common unicode typographic characters.
    """
    if not text:
        return ""
    normalized = unicodedata.normalize("NFKD", text)
    # Replace non-breaking spaces and zero-width spaces
    normalized = normalized.replace("\xa0", " ").replace("\u200b", "")
    # Normalize varied hyphen/dash representations
    normalized = normalized.replace("\u2010", "-").replace("\u2011", "-").replace("\u2012", "-")
    # Replace smart quotes with standard ascii equivalents for robust regex matching
    normalized = normalized.replace("\u2018", "'").replace("\u2019", "'")
    normalized = normalized.replace("\u201c", '"').replace("\u201d", '"')
    return normalized


def load_pdf_pages(pdf_path: str | Path) -> List[PageData]:
    """
    Extracts and normalizes text page-by-page from a PDF file.
    """
    path = Path(pdf_path)
    if not path.exists():
        raise FileNotFoundError(f"PDF file not found: {path}")

    reader = pypdf.PdfReader(str(path))
    pages: List[PageData] = []
    for idx, page in enumerate(reader.pages):
        raw_text = page.extract_text() or ""
        norm_text = normalize_pdf_text(raw_text)
        pages.append(PageData(page_number=idx + 1, raw_text=raw_text, normalized_text=norm_text))
    return pages
