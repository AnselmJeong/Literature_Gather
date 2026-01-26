"""PDF metadata extraction service."""
import logging
import re
import warnings
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pypdf import PdfReader
from pypdf.errors import PdfReadWarning

# Suppress pypdf warnings about malformed PDF metadata
# (common in Elsevier/ScienceDirect PDFs with CrossMarkDomains issues)
warnings.filterwarnings("ignore", category=PdfReadWarning)
logging.getLogger("pypdf").setLevel(logging.ERROR)


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

    Uses pypdf to extract metadata from PDF info dictionary only.
    Full text extraction is not performed - metadata lookup via OpenAlex
    handles DOI/title resolution from filename.
    """

    # Common DOI prefixes for cleaning
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

        # Initialize info
        info = {}
        try:
            reader = PdfReader(str(pdf_path), strict=False)
            info = reader.metadata or {}
        except Exception:
            # If PDF is unreadable, proceed with empty info to use filename fallback
            pass

        # Extract DOI from PDF metadata only
        doi = self._extract_doi_from_metadata(info)

        # Extract title from PDF metadata only
        title = self._extract_title_from_metadata(info)

        # Extract authors from PDF metadata only
        authors = self._extract_authors_from_metadata(info)
        
        # Initialize other fields
        year = None
        pmid = None

        # Fallback: Parse filename if metadata is missing or insufficient
        # Many users name files like "2024 - Author - Title.pdf"
        if not title or len(title) < 5 or not authors:
            filename_meta = self._parse_filename(pdf_path.stem)
            
            if not title or len(title) < 5:
                title = filename_meta.get("title")
            
            if not authors:
                authors = filename_meta.get("authors")
                
            if filename_meta.get("year"):
                year = filename_meta.get("year")

        return PDFMetadata(
            file_path=pdf_path,
            doi=doi,
            title=title,
            authors=authors,
            pmid=pmid,
            year=year,
        )

    def _parse_filename(self, filename: str) -> dict[str, Any]:
        """Parse metadata from filename (format: Year - Author - Title).
        
        Args:
            filename: Filename without extension
            
        Returns:
            Dictionary with extracted metadata
        """
        result = {}
        
        # Try "Year - Author - Title" pattern
        # Split by " - " (space hyphen space)
        parts = filename.split(" - ")
        
        if len(parts) >= 3:
            # Check if first part is a year
            year_part = parts[0].strip()
            if re.match(r"^\d{4}$", year_part):
                result["year"] = int(year_part)
                result["authors"] = [parts[1].strip()]
                # Title is the rest
                result["title"] = " - ".join(parts[2:]).strip()
                return result
                
        if len(parts) == 2:
             # Check if first part is a year "Year - Title"
            year_part = parts[0].strip()
            if re.match(r"^\d{4}$", year_part):
                result["year"] = int(year_part)
                result["title"] = parts[1].strip()
                return result

        # Fallback: Clean up filename and use as title
        # Remove common prefixes/suffixes users might add
        clean_name = filename.replace("_", " ")
        result["title"] = clean_name
        
        return result

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