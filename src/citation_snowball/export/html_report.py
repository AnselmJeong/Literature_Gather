"""HTML report generation for Citation Snowball results."""
import re
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from jinja2 import Template

from citation_snowball.core.models import DownloadResult, DownloadStatus, Paper

if TYPE_CHECKING:
    pass


def sanitize_for_html(text: str | None) -> str:
    """Sanitize text for safe HTML output.

    Args:
        text: Text to sanitize

    Returns:
        Sanitized text safe for HTML
    """
    if not text:
        return ""

    # Basic HTML escaping
    text = text.replace("&", "&amp;")
    text = text.replace("<", "&lt;")
    text = text.replace(">", "&gt;")
    text = text.replace('"', "&quot;")
    text = text.replace("'", "&#39;")

    return text


def format_authors(authors: list) -> str:
    """Format author list for display.

    Args:
        authors: List of AuthorInfo objects

    Returns:
        Formatted author string
    """
    if not authors:
        return "Unknown"

    # Get first few authors
    display_authors = authors[:5]

    names = [a.display_name for a in display_authors if a.display_name]

    if len(names) == 0:
        return "Unknown"

    if len(authors) > 5:
        names.append("et al.")

    return ", ".join(names)


def get_google_scholar_url(title: str | None) -> str:
    """Get Google Scholar search URL for a paper.

    Args:
        title: Paper title

    Returns:
        Google Scholar URL
    """
    if not title:
        return "https://scholar.google.com"

    from urllib.parse import quote

    return f"https://scholar.google.com/scholar?q={quote(title)}"


def get_scihub_url(doi: str | None) -> str | None:
    """Get Sci-Hub URL for a paper.

    Note: This is provided for informational purposes only.

    Args:
        doi: Paper DOI

    Returns:
        Sci-Hub URL if DOI available, None otherwise
    """
    if not doi:
        return None

    from urllib.parse import quote

    return f"https://sci-hub.se/{quote(doi)}"


# HTML Template for download report
DOWNLOAD_REPORT_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Citation Snowball - Download Report</title>
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }

        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, sans-serif;
            line-height: 1.6;
            color: #333;
            background-color: #f5f5f5;
            padding: 20px;
        }

        .container {
            max-width: 900px;
            margin: 0 auto;
            background: white;
            border-radius: 8px;
            box-shadow: 0 2px 10px rgba(0,0,0,0.1);
            overflow: hidden;
        }

        .header {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 30px;
        }

        .header h1 {
            font-size: 28px;
            margin-bottom: 10px;
        }

        .header .subtitle {
            opacity: 0.9;
            font-size: 14px;
        }

        .summary {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
            gap: 15px;
            padding: 20px;
            background: #f8f9fa;
            border-bottom: 1px solid #e9ecef;
        }

        .summary-item {
            text-align: center;
        }

        .summary-item .value {
            font-size: 24px;
            font-weight: bold;
            color: #667eea;
        }

        .summary-item .label {
            font-size: 12px;
            color: #6c757d;
            text-transform: uppercase;
        }

        .section {
            padding: 20px;
        }

        .section h2 {
            font-size: 18px;
            margin-bottom: 15px;
            color: #495057;
            border-bottom: 2px solid #667eea;
            padding-bottom: 10px;
        }

        .paper {
            padding: 15px;
            margin-bottom: 15px;
            border-radius: 6px;
            border: 1px solid #dee2e6;
        }

        .paper.failed {
            background-color: #fff3cd;
            border-color: #ffc107;
        }

        .paper.success {
            background-color: #d4edda;
            border-color: #28a745;
        }

        .paper-title {
            font-weight: 600;
            font-size: 16px;
            margin-bottom: 8px;
            color: #212529;
        }

        .paper-meta {
            font-size: 13px;
            color: #6c757d;
            margin-bottom: 10px;
        }

        .paper-links {
            display: flex;
            gap: 10px;
            flex-wrap: wrap;
            margin-top: 10px;
        }

        .paper-links a {
            display: inline-block;
            padding: 5px 12px;
            background: #007bff;
            color: white;
            text-decoration: none;
            border-radius: 4px;
            font-size: 12px;
        }

        .paper-links a:hover {
            background: #0056b3;
        }

        .paper-links a.secondary {
            background: #6c757d;
        }

        .paper-links a.secondary:hover {
            background: #545b62;
        }

        .paper-reason {
            margin-top: 10px;
            padding: 8px 12px;
            background: rgba(0,0,0,0.05);
            border-radius: 4px;
            font-size: 13px;
            color: #856404;
        }

        .empty {
            text-align: center;
            padding: 40px;
            color: #6c757d;
        }

        .footer {
            padding: 20px;
            text-align: center;
            font-size: 12px;
            color: #6c757d;
            border-top: 1px solid #e9ecef;
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>Download Report</h1>
            <div class="subtitle">
                Generated: {{ timestamp }} |
                Project: {{ project_name }}
            </div>
        </div>

        <div class="summary">
            <div class="summary-item">
                <div class="value">{{ total }}</div>
                <div class="label">Total Papers</div>
            </div>
            <div class="summary-item">
                <div class="value">{{ success_count }}</div>
                <div class="label">Downloaded</div>
            </div>
            <div class="summary-item">
                <div class="value">{{ failed_count }}</div>
                <div class="label">Failed</div>
            </div>
            <div class="summary-item">
                <div class="value">{{ success_rate }}%</div>
                <div class="label">Success Rate</div>
            </div>
        </div>

        {% if failed_papers %}
        <div class="section">
            <h2>Papers Requiring Manual Download ({{ failed_papers|length }})</h2>
            {% for paper in failed_papers %}
            <div class="paper failed">
                <div class="paper-title">{{ paper.title }}</div>
                <div class="paper-meta">
                    {{ paper.authors }} ({{ paper.year }}) — {{ paper.journal or 'Unknown Journal' }}
                </div>
                <div class="paper-links">
                    {% if paper.doi_url %}
                    <a href="{{ paper.doi_url }}" target="_blank">DOI</a>
                    {% endif %}
                    {% if paper.google_scholar_url %}
                    <a href="{{ paper.google_scholar_url }}" target="_blank">Google Scholar</a>
                    {% endif %}
                    {% if paper.scihub_url %}
                    <a href="{{ paper.scihub_url }}" target="_blank" class="secondary">Sci-Hub</a>
                    {% endif %}
                    <a href="https://www.google.com/search?q={{ paper.search_query }}" target="_blank" class="secondary">Search</a>
                </div>
                <div class="paper-reason">
                    <strong>Reason:</strong> {{ paper.failure_reason }}
                </div>
            </div>
            {% endfor %}
        </div>
        {% endif %}

        {% if success_papers %}
        <div class="section">
            <h2>Successfully Downloaded ({{ success_papers|length }})</h2>
            {% for paper in success_papers %}
            <div class="paper success">
                <div class="paper-title">{{ paper.title }}</div>
                <div class="paper-meta">
                    {{ paper.authors }} ({{ paper.year }})
                </div>
                <div class="paper-reason">
                    <strong>Saved:</strong> {{ paper.file_path }}
                </div>
            </div>
            {% endfor %}
        </div>
        {% endif %}

        <div class="footer">
            Generated by Citation Snowball — {{ timestamp }}
        </div>
    </div>
</body>
</html>
"""

# HTML Template for collection report
COLLECTION_REPORT_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Citation Snowball - Collection Report</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            line-height: 1.6;
            color: #333;
            padding: 20px;
        }
        .container { max-width: 1200px; margin: 0 auto; }
        .header {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 30px;
            border-radius: 8px 8px 0 0;
        }
        .summary {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
            gap: 15px;
            padding: 20px;
            background: #f8f9fa;
            border: 1px solid #e9ecef;
            border-top: none;
        }
        .summary-item { text-align: center; }
        .summary-item .value { font-size: 24px; font-weight: bold; color: #667eea; }
        .summary-item .label { font-size: 12px; color: #6c757d; text-transform: uppercase; }

        table { width: 100%; border-collapse: collapse; }
        th, td { padding: 12px; text-align: left; border-bottom: 1px solid #dee2e6; }
        th { background: #f8f9fa; font-weight: 600; color: #495057; }
        tr:hover { background: #f8f9fa; }

        .score-badge {
            display: inline-block;
            padding: 2px 8px;
            border-radius: 12px;
            font-size: 12px;
            font-weight: 600;
        }
        .score-high { background: #d4edda; color: #155724; }
        .score-medium { background: #fff3cd; color: #856404; }
        .score-low { background: #f8d7da; color: #721c24; }

        .method-badge {
            display: inline-block;
            padding: 2px 8px;
            border-radius: 4px;
            font-size: 11px;
            text-transform: uppercase;
        }
        .method-seed { background: #667eea; color: white; }
        .method-forward { background: #28a745; color: white; }
        .method-backward { background: #17a2b8; color: white; }
        .method-author { background: #fd7e14; color: white; }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>{{ project_name }}</h1>
            <p>{{ papers|length }} papers collected | Generated: {{ timestamp }}</p>
        </div>
        <div class="summary">
            <div class="summary-item"><div class="value">{{ papers|length }}</div><div class="label">Total Papers</div></div>
            <div class="summary-item"><div class="value">{{ iteration_count }}</div><div class="label">Iterations</div></div>
            <div class="summary-item"><div class="value">{{ avg_score|round(2) }}</div><div class="label">Avg Score</div></div>
            <div class="summary-item"><div class="value">{{ avg_citations|round(1) }}</div><div class="label">Avg Citations</div></div>
        </div>
        <table>
            <thead>
                <tr>
                    <th>Score</th>
                    <th>Title</th>
                    <th>Authors</th>
                    <th>Year</th>
                    <th>Citations</th>
                    <th>Method</th>
                    <th>DOI</th>
                </tr>
            </thead>
            <tbody>
                {% for paper in papers %}
                <tr>
                    <td><span class="score-badge {{ paper.score_class }}">{{ paper.score|round(2) }}</span></td>
                    <td>{{ paper.title }}</td>
                    <td>{{ paper.authors_short }}</td>
                    <td>{{ paper.year or '-' }}</td>
                    <td>{{ paper.citations or 0 }}</td>
                    <td><span class="method-badge method-{{ paper.method }}">{{ paper.method }}</span></td>
                    <td>{% if paper.doi %}<a href="https://doi.org/{{ paper.doi }}" target="_blank">{{ paper.doi }}</a>{% else %}-{% endif %}</td>
                </tr>
                {% endfor %}
            </tbody>
        </table>
    </div>
</body>
</html>
"""


class HTMLReportGenerator:
    """Generate HTML reports for Citation Snowball results."""

    def __init__(self):
        """Initialize report generator."""
        self.download_template = Template(DOWNLOAD_REPORT_TEMPLATE)
        self.collection_template = Template(COLLECTION_REPORT_TEMPLATE)

    def generate_download_report(
        self,
        results: list[DownloadResult],
        papers: dict[str, Paper],
        project_name: str,
        output_path: Path,
    ) -> None:
        """Generate HTML report for download results.

        Args:
            results: Download results
            papers: Dictionary mapping paper IDs to Paper objects
            project_name: Name of the project
            output_path: Path to save the HTML report
        """
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # Separate successes and failures
        success_papers = []
        failed_papers = []

        for result in results:
            paper = papers.get(result.paper_id)

            if result.success:
                if paper:
                    success_papers.append(
                        {
                            "title": sanitize_for_html(paper.title),
                            "authors": sanitize_for_html(format_authors(paper.authors)),
                            "year": paper.publication_year or "Unknown",
                            "file_path": str(result.file_path) if result.file_path else "Unknown",
                        }
                    )
            else:
                if paper:
                    doi_url = (
                        f"https://doi.org/{paper.doi}" if paper.doi else None
                    )
                    google_scholar_url = get_google_scholar_url(paper.title)
                    scihub_url = get_scihub_url(paper.doi)

                    failed_papers.append(
                        {
                            "title": sanitize_for_html(paper.title),
                            "authors": sanitize_for_html(format_authors(paper.authors)),
                            "year": paper.publication_year or "Unknown",
                            "journal": sanitize_for_html(paper.journal),
                            "doi_url": doi_url,
                            "google_scholar_url": google_scholar_url,
                            "scihub_url": scihub_url,
                            "search_query": sanitize_for_html(paper.title or ""),
                            "failure_reason": sanitize_for_html(result.error_message or "Unknown"),
                        }
                    )

        # Sort failed papers by score (highest first) to prioritize manual download
        if failed_papers:
            # Would need score info - for now just keep as is
            pass

        # Calculate statistics
        total = len(results)
        success_count = len(success_papers)
        failed_count = len(failed_papers)
        success_rate = (success_count / total * 100) if total > 0 else 0

        # Generate HTML
        html = self.download_template.render(
            timestamp=timestamp,
            project_name=sanitize_for_html(project_name),
            total=total,
            success_count=success_count,
            failed_count=failed_count,
            success_rate=round(success_rate, 1),
            failed_papers=failed_papers,
            success_papers=success_papers,
        )

        # Write to file
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(html, encoding="utf-8")

    def generate_collection_report(
        self,
        papers: list[Paper],
        project_name: str,
        iteration_count: int,
        output_path: Path,
    ) -> None:
        """Generate HTML report for the collected papers.

        Args:
            papers: List of collected papers
            project_name: Name of the project
            iteration_count: Number of iterations completed
            output_path: Path to save the HTML report
        """
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # Prepare paper data
        paper_data = []
        total_score = 0
        total_citations = 0

        for paper in papers:
            # Get score class for styling
            if paper.score >= 0.7:
                score_class = "score-high"
            elif paper.score >= 0.4:
                score_class = "score-medium"
            else:
                score_class = "score-low"

            # Format authors
            authors_short = format_authors(paper.authors[:3])
            if len(paper.authors) > 3:
                authors_short += " et al."

            paper_data.append(
                {
                    "title": sanitize_for_html(paper.title),
                    "authors_short": sanitize_for_html(authors_short),
                    "year": paper.publication_year,
                    "citations": paper.cited_by_count,
                    "score": paper.score,
                    "score_class": score_class,
                    "method": paper.discovery_method.value,
                    "doi": paper.doi,
                }
            )

            total_score += paper.score
            total_citations += paper.cited_by_count

        # Calculate averages
        avg_score = total_score / len(papers) if papers else 0
        avg_citations = total_citations / len(papers) if papers else 0

        # Sort by score (descending)
        paper_data.sort(key=lambda x: x["score"], reverse=True)

        # Generate HTML
        html = self.collection_template.render(
            timestamp=timestamp,
            project_name=sanitize_for_html(project_name),
            papers=paper_data,
            iteration_count=iteration_count,
            avg_score=avg_score,
            avg_citations=avg_citations,
        )

        # Write to file
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(html, encoding="utf-8")