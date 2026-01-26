"""Repository layer for database operations."""
import json
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from citation_snowball.core.models import (
    AuthorInfo,
    DiscoveryMethod,
    DownloadStatus,
    IterationMetrics,
    Paper,
    Project,
    ProjectConfig,
    ScoreBreakdown,
    YearCount,
)
from citation_snowball.db.database import Database


def _generate_id() -> str:
    """Generate a unique ID."""
    return str(uuid.uuid4())


def _serialize_json(obj: Any) -> str:
    """Serialize object to JSON string."""
    if hasattr(obj, "model_dump"):
        return json.dumps(obj.model_dump(mode="json"))
    return json.dumps(obj, default=str)


def _row_to_project(row: Any) -> Project:
    """Convert database row to Project model."""
    config_data = json.loads(row["config"])
    return Project(
        id=row["id"],
        name=row["name"],
        created_at=datetime.fromisoformat(row["created_at"]),
        updated_at=datetime.fromisoformat(row["updated_at"]),
        config=ProjectConfig(**config_data),
        current_iteration=row["current_iteration"],
        is_complete=bool(row["is_complete"]),
    )


def _row_to_paper(row: Any) -> Paper:
    """Convert database row to Paper model."""
    authors_data = json.loads(row["authors"]) if row["authors"] else []
    authors = [AuthorInfo(**a) for a in authors_data]

    counts_data = json.loads(row["counts_by_year"]) if row["counts_by_year"] else []
    counts_by_year = [YearCount(**c) for c in counts_data]

    referenced = json.loads(row["referenced_works"]) if row["referenced_works"] else []
    discovered_from = json.loads(row["discovered_from"]) if row["discovered_from"] else []

    score_components = None
    if row["score_components"]:
        score_components = ScoreBreakdown(**json.loads(row["score_components"]))

    return Paper(
        id=row["id"],
        openalex_id=row["openalex_id"],
        doi=row["doi"],
        pmid=row["pmid"],
        title=row["title"],
        authors=authors,
        publication_year=row["publication_year"],
        journal=row["journal"],
        abstract=row["abstract"],
        language=row["language"],
        type=row["type"],
        cited_by_count=row["cited_by_count"],
        counts_by_year=counts_by_year,
        referenced_works=referenced,
        score=row["score"] or 0.0,
        score_components=score_components,
        discovery_method=DiscoveryMethod(row["discovery_method"]) if row["discovery_method"] else DiscoveryMethod.SEED,
        discovered_from=discovered_from,
        iteration_added=row["iteration_added"] or 0,
        download_status=DownloadStatus(row["download_status"]) if row["download_status"] else DownloadStatus.PENDING,
        local_path=Path(row["local_path"]) if row["local_path"] else None,
        oa_url=row["oa_url"],
        created_at=datetime.fromisoformat(row["created_at"]),
    )


class ProjectRepository:
    """Repository for Project operations."""

    def __init__(self, db: Database):
        self.db = db

    def create(self, name: str, config: ProjectConfig | None = None) -> Project:
        """Create a new project."""
        project_id = _generate_id()
        now = datetime.now()
        cfg = config or ProjectConfig()

        self.db.execute(
            """
            INSERT INTO projects (id, name, created_at, updated_at, config, current_iteration, is_complete)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (project_id, name, now.isoformat(), now.isoformat(), _serialize_json(cfg), 0, 0),
        )

        return Project(
            id=project_id,
            name=name,
            created_at=now,
            updated_at=now,
            config=cfg,
        )

    def get(self, project_id: str) -> Project | None:
        """Get a project by ID."""
        row = self.db.fetchone("SELECT * FROM projects WHERE id = ?", (project_id,))
        return _row_to_project(row) if row else None

    def get_by_name(self, name: str) -> Project | None:
        """Get a project by name."""
        row = self.db.fetchone("SELECT * FROM projects WHERE name = ?", (name,))
        return _row_to_project(row) if row else None

    def list_all(self) -> list[Project]:
        """List all projects."""
        rows = self.db.fetchall("SELECT * FROM projects ORDER BY updated_at DESC")
        return [_row_to_project(row) for row in rows]

    def update(self, project: Project) -> None:
        """Update a project."""
        project.updated_at = datetime.now()
        self.db.execute(
            """
            UPDATE projects
            SET name = ?, updated_at = ?, config = ?, current_iteration = ?, is_complete = ?
            WHERE id = ?
            """,
            (
                project.name,
                project.updated_at.isoformat(),
                _serialize_json(project.config),
                project.current_iteration,
                int(project.is_complete),
                project.id,
            ),
        )

    def delete(self, project_id: str) -> None:
        """Delete a project and all related data."""
        self.db.execute("DELETE FROM projects WHERE id = ?", (project_id,))


class PaperRepository:
    """Repository for Paper operations."""

    def __init__(self, db: Database):
        self.db = db

    def create(self, project_id: str, paper: Paper) -> Paper:
        """Create a new paper record."""
        # Check if already exists to prevent duplicates
        existing = self.get_by_openalex_id(project_id, paper.openalex_id)
        if existing:
            return existing

        if not paper.id:
            paper.id = _generate_id()

        self.db.execute(
            """
            INSERT INTO papers (
                id, project_id, openalex_id, doi, pmid, title, authors,
                publication_year, journal, abstract, language, type,
                cited_by_count, counts_by_year, referenced_works,
                score, score_components, discovery_method, discovered_from, iteration_added,
                download_status, local_path, oa_url, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                paper.id,
                project_id,
                paper.openalex_id,
                paper.doi,
                paper.pmid,
                paper.title,
                json.dumps([a.model_dump() for a in paper.authors]),
                paper.publication_year,
                paper.journal,
                paper.abstract,
                paper.language,
                paper.type,
                paper.cited_by_count,
                json.dumps([c.model_dump() for c in paper.counts_by_year]),
                json.dumps(paper.referenced_works),
                paper.score,
                _serialize_json(paper.score_components) if paper.score_components else None,
                paper.discovery_method.value,
                json.dumps(paper.discovered_from),
                paper.iteration_added,
                paper.download_status.value,
                str(paper.local_path) if paper.local_path else None,
                paper.oa_url,
                paper.created_at.isoformat(),
            ),
        )
        return paper

    def get(self, paper_id: str) -> Paper | None:
        """Get a paper by ID."""
        row = self.db.fetchone("SELECT * FROM papers WHERE id = ?", (paper_id,))
        return _row_to_paper(row) if row else None

    def get_by_openalex_id(self, project_id: str, openalex_id: str) -> Paper | None:
        """Get a paper by OpenAlex ID within a project."""
        row = self.db.fetchone(
            "SELECT * FROM papers WHERE project_id = ? AND openalex_id = ?",
            (project_id, openalex_id),
        )
        return _row_to_paper(row) if row else None

    def exists(self, project_id: str, openalex_id: str) -> bool:
        """Check if a paper exists in the project."""
        row = self.db.fetchone(
            "SELECT 1 FROM papers WHERE project_id = ? AND openalex_id = ?",
            (project_id, openalex_id),
        )
        return row is not None

    def list_by_project(
        self,
        project_id: str,
        sort_by: str = "score",
        descending: bool = True,
        limit: int | None = None,
    ) -> list[Paper]:
        """List papers for a project."""
        order = "DESC" if descending else "ASC"
        sql = f"SELECT * FROM papers WHERE project_id = ? ORDER BY {sort_by} {order}"
        if limit:
            sql += f" LIMIT {limit}"
        rows = self.db.fetchall(sql, (project_id,))
        return [_row_to_paper(row) for row in rows]

    def list_by_iteration(self, project_id: str, iteration: int) -> list[Paper]:
        """List papers added in a specific iteration."""
        rows = self.db.fetchall(
            "SELECT * FROM papers WHERE project_id = ? AND iteration_added = ? ORDER BY score DESC",
            (project_id, iteration),
        )
        return [_row_to_paper(row) for row in rows]

    def list_seeds(self, project_id: str) -> list[Paper]:
        """List seed papers for a project."""
        rows = self.db.fetchall(
            "SELECT * FROM papers WHERE project_id = ? AND discovery_method = 'seed' ORDER BY title",
            (project_id,),
        )
        return [_row_to_paper(row) for row in rows]

    def count(self, project_id: str) -> int:
        """Count papers in a project."""
        row = self.db.fetchone("SELECT COUNT(*) as cnt FROM papers WHERE project_id = ?", (project_id,))
        return row["cnt"] if row else 0

    def update_score(self, paper_id: str, score: float, components: ScoreBreakdown) -> None:
        """Update paper score."""
        self.db.execute(
            "UPDATE papers SET score = ?, score_components = ? WHERE id = ?",
            (score, _serialize_json(components), paper_id),
        )

    def update_download_status(
        self,
        paper_id: str,
        status: DownloadStatus,
        local_path: Path | None = None,
    ) -> None:
        """Update paper download status."""
        self.db.execute(
            "UPDATE papers SET download_status = ?, local_path = ? WHERE id = ?",
            (status.value, str(local_path) if local_path else None, paper_id),
        )

    def get_all_openalex_ids(self, project_id: str) -> set[str]:
        """Get all OpenAlex IDs in a project."""
        rows = self.db.fetchall("SELECT openalex_id FROM papers WHERE project_id = ?", (project_id,))
        return {row["openalex_id"] for row in rows}

    def delete(self, paper_id: str) -> None:
        """Delete a paper."""
        self.db.execute("DELETE FROM papers WHERE id = ?", (paper_id,))


class IterationRepository:
    """Repository for Iteration operations."""

    def __init__(self, db: Database):
        self.db = db

    def create(self, project_id: str, iteration_number: int) -> str:
        """Create a new iteration record."""
        # Check if already exists
        existing = self.db.fetchone(
            "SELECT id FROM iterations WHERE project_id = ? AND iteration_number = ?",
            (project_id, iteration_number),
        )
        if existing:
            return existing["id"]

        iteration_id = _generate_id()
        self.db.execute(
            """
            INSERT INTO iterations (id, project_id, iteration_number, started_at)
            VALUES (?, ?, ?, ?)
            """,
            (iteration_id, project_id, iteration_number, datetime.now().isoformat()),
        )
        return iteration_id

    def complete(self, iteration_id: str, metrics: IterationMetrics) -> None:
        """Mark iteration as complete with metrics."""
        self.db.execute(
            "UPDATE iterations SET completed_at = ?, metrics = ? WHERE id = ?",
            (datetime.now().isoformat(), _serialize_json(metrics), iteration_id),
        )

    def list_by_project(self, project_id: str) -> list[dict[str, Any]]:
        """List iterations for a project."""
        rows = self.db.fetchall(
            "SELECT * FROM iterations WHERE project_id = ? ORDER BY iteration_number",
            (project_id,),
        )
        return [dict(row) for row in rows]


class CacheRepository:
    """Repository for API response caching."""

    def __init__(self, db: Database):
        self.db = db

    def get(self, cache_key: str) -> dict[str, Any] | None:
        """Get cached response if not expired."""
        row = self.db.fetchone(
            "SELECT response FROM api_cache WHERE cache_key = ? AND expires_at > ?",
            (cache_key, datetime.now().isoformat()),
        )
        if row:
            return json.loads(row["response"])
        return None

    def set(self, cache_key: str, response: dict[str, Any], ttl_days: int = 7) -> None:
        """Cache a response."""
        expires_at = datetime.now() + timedelta(days=ttl_days)
        self.db.execute(
            """
            INSERT OR REPLACE INTO api_cache (cache_key, response, cached_at, expires_at)
            VALUES (?, ?, ?, ?)
            """,
            (cache_key, json.dumps(response), datetime.now().isoformat(), expires_at.isoformat()),
        )

    def delete(self, cache_key: str) -> None:
        """Delete a cache entry."""
        self.db.execute("DELETE FROM api_cache WHERE cache_key = ?", (cache_key,))

    def clear_expired(self) -> int:
        """Clear expired cache entries. Returns count deleted."""
        cursor = self.db.execute(
            "DELETE FROM api_cache WHERE expires_at < ?",
            (datetime.now().isoformat(),),
        )
        return cursor.rowcount
