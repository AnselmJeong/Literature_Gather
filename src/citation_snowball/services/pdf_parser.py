"""PDF metadata extraction service."""
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pypdf import PdfReader


@dataclass
class PDFMetadata:
    """Extracted metadata from a PDF file."""

    file_path: Path
    doi: str | None = None
    title: str | None = None
    authors: list[str] | None = None
    pmid: str | None = None
    year: int | None = None


class PDFParser:
    """Extract metadata from PDF files.

    Uses pypdf with fallback strategies for various PDF formats.
    """

    # DOI regex pattern - matches standard DOI format
    DOI_PATTERN = re.compile(
        r"10\.\d{4,9}/[-._;()/:A-Z0-9]+",
        re.IGNORECASE,
    )

    # PMID pattern - PubMed ID
    PMID_PATTERN = re.compile(r"\bPMID:\s*(\d+)\b", re.IGNORECASE)

    # Year pattern - 4 digit year in reasonable range
    YEAR_PATTERN = re.compile(r"\b(19|20)\d{2}\b")

    # Common DOI prefixes for easier matching
    DOI_PREFIXES = [
        "doi:",
        "doi.org/",
        "dx.doi.org/",
        "https://doi.org/",
        "http://doi.org/",
    ]

    def __init__(self):
        """Initialize PDF parser."""
        pass

    def extract_from_file(self, pdf_path: Path) -> PDFMetadata:
        """Extract metadata from a PDF file.

        Args:
            pdf_path: Path to the PDF file

        Returns:
            PDFMetadata with extracted information

        Raises:
            FileNotFoundError: If PDF file doesn't exist
            ValueError: If file is not a valid PDF
        """
        if not pdf_path.exists():
            raise FileNotFoundError(f"PDF file not found: {pdf_path}")

        if not pdf_path.suffix.lower() == ".pdf":
            raise ValueError(f"File is not a PDF: {pdf_path}")

        try:
            reader = PdfReader(str(pdf_path))
        except Exception as e:
            raise ValueError(f"Failed to read PDF file: {e}")

        # Extract text from all pages
        all_text = self._extract_all_text(reader)

        # Try metadata from PDF info first
        info = reader.metadata or {}

        # Extract DOI - check PDF metadata first, then full text
        doi = self._extract_doi_from_metadata(info) or self._extract_doi_from_text(
            all_text
        )

        # Extract title
        title = self._extract_title_from_metadata(info) or self._extract_title_from_text(
            all_text
        )

        # Extract authors
        authors = self._extract_authors_from_metadata(info) or self._extract_authors_from_text(
            all_text
        )

        # Extract PMID
        pmid = self._extract_pmid(all_text)

        # Extract year
        year = self._extract_year(all_text)

        return PDFMetadata(
            file_path=pdf_path,
            doi=doi,
            title=title,
            authors=authors,
            pmid=pmid,
            year=year,
        )

    def _extract_all_text(self, reader: PdfReader) -> str:
        """Extract text from all pages of a PDF.

        Args:
            reader: PdfReader instance

        Returns:
            Combined text from all pages
        """
        text_parts = []

        for page in reader.pages:
            try:
                text_parts.append(page.extract_text() or "")
            except Exception:
                continue

        return "\n".join(text_parts)

    def _extract_doi_from_metadata(self, metadata: dict[str, Any]) -> str | None:
        """Extract DOI from PDF metadata.

        Args:
            metadata: PDF metadata dictionary

        Returns:
            DOI string if found, None otherwise
        """
        # Check common metadata keys
        for key in ["/doi", "/DOI", "doi", "DOI"]:
            if key in metadata:
                doi = str(metadata[key]).strip()
                if doi and not doi.startswith("/"):
                    return self._clean_doi(doi)

        return None

    def _extract_doi_from_text(self, text: str) -> str | None:
        """Extract DOI from PDF text content.

        Args:
            text: Full text from PDF

        Returns:
            DOI string if found, None otherwise
        """
        # Look for DOI pattern
        matches = self.DOI_PATTERN.findall(text)

        for match in matches:
            cleaned = self._clean_doi(match)
            if cleaned:
                return cleaned

        return None

    def _clean_doi(self, doi: str) -> str | None:
        """Clean and normalize DOI string.

        Args:
            doi: Raw DOI string

        Returns:
            Cleaned DOI string, or None if invalid
        """
        # Remove common prefixes
        for prefix in self.DOI_PREFIXES:
            if doi.lower().startswith(prefix.lower()):
                doi = doi[len(prefix) :]
                break

        # Strip whitespace and trailing punctuation
        doi = doi.strip().strip(".,;:)(")

        # Validate it's a reasonable DOI
        if not re.match(r"^10\.\d{4,9}/[-._;()/:A-Z0-9]+$", doi, re.IGNORECASE):
            return None

        return doi

    def _extract_title_from_metadata(self, metadata: dict[str, Any]) -> str | None:
        """Extract title from PDF metadata.

        Args:
            metadata: PDF metadata dictionary

        Returns:
            Title string if found, None otherwise
        """
        for key in ["/Title", "/title", "Title", "title"]:
            if key in metadata:
                title = str(metadata[key]).strip()
                if title and not title.startswith("/"):
                    # Remove PDF encoding artifacts
                    title = title.replace("\\", "")
                    if len(title) > 10:  # Minimum reasonable title length
                        return title

        return None

    def _extract_title_from_text(self, text: str) -> str | None:
        """Extract title from PDF text content.

        This is heuristic - looks for likely title candidates near the beginning.

        Args:
            text: Full text from PDF

        Returns:
            Title string if found, None otherwise
        """
        # Get first few lines
        lines = text.split("\n")[:50]

        # Look for the longest non-empty line (often the title)
        candidates = []

        for line in lines:
            line = line.strip()
            # Skip very short or very long lines
            if 10 < len(line) < 200:
                # Skip lines that look like headers/footers
                if not re.search(r"^\d+\s*$|^page|^©|^http", line, re.IGNORECASE):
                    candidates.append(line)

        if candidates:
            # Return the longest candidate (often the title)
            return max(candidates, key=len)

        return None

    def _extract_authors_from_metadata(self, metadata: dict[str, Any]) -> list[str] | None:
        """Extract authors from PDF metadata.

        Args:
            metadata: PDF metadata dictionary

        Returns:
            List of author names if found, None otherwise
        """
        for key in ["/Author", "/author", "Author", "author"]:
            if key in metadata:
                authors_str = str(metadata[key]).strip()
                if authors_str and not authors_str.startswith("/"):
                    # Clean up PDF encoding artifacts
                    authors_str = authors_str.replace("\\", "")

                    # Parse common author formats
                    authors = self._parse_author_string(authors_str)
                    if authors:
                        return authors

        return None

    def _extract_authors_from_text(self, text: str) -> list[str] | None:
        """Extract authors from PDF text content.

        This is heuristic - looks for author patterns near title.

        Args:
            text: Full text from PDF

        Returns:
            List of author names if found, None otherwise
        """
        # Look for author patterns in first portion of text
        first_portion = "\n".join(text.split("\n")[:100])

        # Pattern for "Author Name" or "Name, Initial"
        author_pattern = re.compile(
            r"(?:^|\n)\s*([A-Z][a-z]+(?:\s+[A-Z]\.?\s*)+(?:,\s*[A-Z]\.?\s*)*)",
            re.MULTILINE,
        )

        matches = author_pattern.findall(first_portion)

        if matches:
            # Filter out common false positives
            authors = []
            for match in matches[:10]:  # Limit to first 10 matches
                match = match.strip()
                # Skip if it looks like a title or header
                if not re.match(r"^(Abstract|Introduction|Keywords|References)", match, re.IGNORECASE):
                    authors.append(match)

            if authors:
                return authors[:5]  # Limit to 5 authors

        return None

    def _parse_author_string(self, authors_str: str) -> list[str]:
        """Parse author string into list of names.

        Args:
            authors_str: Raw author string

        Returns:
            List of author names
        """
        # Try common separators
        for sep in [" and ", ";", ", "]:
            if sep in authors_str:
                names = [name.strip() for name in authors_str.split(sep)]
                # Filter out empty strings
                names = [name for name in names if name]
                if names:
                    return names

        # If no separator found, treat as single author
        if authors_str:
            return [authors_str]

        return []

    def _extract_pmid(self, text: str) -> str | None:
        """Extract PMID from PDF text.

        Args:
            text: Full text from PDF

        Returns:
            PMID string if found, None otherwise
        """
        match = self.PMID_PATTERN.search(text)
        if match:
            return match.group(1)

        return None

    def _extract_year(self, text: str) -> int | None:
        """Extract publication year from PDF text.

        Args:
            text: Full text from PDF

        Returns:
            Year as integer if found, None otherwise
        """
        # Look for years in first portion of text
        first_portion = "\n".join(text.split("\n")[:50])

        matches = self.YEAR_PATTERN.findall(first_portion)

        if matches:
            # Get the most recent year (but not future year)
            current_year = 2026  # Update as needed
            valid_years = [int(m) for m in matches if int(m) <= current_year and int(m) >= 1990]

            if valid_years:
                # Return the maximum (most recent) valid year
                return max(valid_years)

        return None