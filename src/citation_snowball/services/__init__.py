"""API and service modules for Citation Snowball."""
from citation_snowball.services.crossref import CrossrefClient, CrossrefWork
from citation_snowball.services.downloader import PDFDownloader
from citation_snowball.services.openalex import OpenAlexClient
from citation_snowball.services.pdf_parser import PDFMetadata, PDFParser
from citation_snowball.services.unpaywall import OAInfo, UnpaywallClient

__all__ = [
    "OpenAlexClient",
    "UnpaywallClient",
    "CrossrefClient",
    "CrossrefWork",
    "PDFParser",
    "PDFMetadata",
    "OAInfo",
    "PDFDownloader",
]
