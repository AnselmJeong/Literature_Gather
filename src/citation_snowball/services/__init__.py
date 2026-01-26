"""API and service modules for Citation Snowball."""
from citation_snowball.services.crossref import CrossrefClient, CrossrefWork
from citation_snowball.services.downloader import PDFDownloader
from citation_snowball.services.semantic_scholar import SemanticScholarClient
from citation_snowball.services.pdf_parser import PDFMetadata, PDFParser
from citation_snowball.services.unpaywall import OAInfo, UnpaywallClient

__all__ = [
    "SemanticScholarClient",
    "UnpaywallClient",
    "CrossrefClient",
    "CrossrefWork",
    "PDFParser",
    "PDFMetadata",
    "OAInfo",
    "PDFDownloader",
]