"""Rule-based snowball expansion engine."""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

from citation_snowball.core.models import (
    DiscoveryMethod,
    IterationMetrics,
    Paper,
    Project,
    Work,
)
from citation_snowball.db.repository import (
    IterationRepository,
    PaperRepository,
    ProjectRepository,
)
from citation_snowball.services.openalex import OpenAlexClient


class SnowballEngine:
    """Snowball engine with ref_counter-seeded expansion rules."""

    def __init__(
        self,
        project: Project,
        api_client: OpenAlexClient,
        paper_repo: PaperRepository,
        iteration_repo: IterationRepository,
        seed_directory: Path | None = None,
    ):
        self.project = project
        self.api_client = api_client
        self.paper_repo = paper_repo
        self.iteration_repo = iteration_repo
        self.seed_directory = seed_directory

        self.working_set: list[Paper] = []
        self.all_collected: list[Paper] = []
        self._stop_requested = False

        # OpenAlex lookup cache to avoid repeated searches
        self._work_cache: dict[str, Work | None] = {}
        self._references_cache: dict[str, set[str]] = {}
        self._citers_cache: dict[str, set[str]] = {}

    async def run(self, progress_callback=None) -> IterationMetrics | None:
        """Run recursive expansion."""
        await self._initialize()
        if not self.working_set:
            raise ValueError("No seed papers found")

        await self._bootstrap_from_ref_counter()

        recursion_limit = (
            self.project.config.no_recursion
            if self.project.config.no_recursion is not None
            else self.project.config.max_iterations
        )

        final_metrics: IterationMetrics | None = None

        for iteration in range(1, recursion_limit + 1):
            if self._stop_requested:
                break

            self.project.current_iteration = iteration
            metrics = await self._run_iteration(iteration)
            final_metrics = metrics

            if progress_callback:
                await progress_callback(iteration, metrics)

            # Stop when no additional seeds were created
            if metrics.new_papers == 0:
                self.project.is_complete = True
                ProjectRepository(self.paper_repo.db).update(self.project)
                break

            ProjectRepository(self.paper_repo.db).update(self.project)

        return final_metrics

    def stop(self) -> None:
        self._stop_requested = True

    async def _initialize(self) -> None:
        self.working_set = self.paper_repo.list_seeds(self.project.id)
        self.all_collected = self.paper_repo.list_by_project(self.project.id)

    async def _bootstrap_from_ref_counter(self) -> None:
        """Step 1-4: build initial recursive seed set from ref_counter output."""
        if not self.seed_directory:
            return

        data = self._run_ref_counter(self.seed_directory)
        if not data:
            return

        seed_ids = set(data.get("source_openalex_ids", []))

        ref_ids: set[str] = set()
        for ref in data.get("aggregate_references", []):
            openalex_id = ref.get("openalex_id")
            if not openalex_id:
                continue
            if ref.get("cited_by_n_seed_papers", 0) >= 2 or ref.get(
                "max_mentions_in_single_paper", 0
            ) >= 3:
                ref_ids.add(openalex_id)

        initial_recursive_seed_ids = seed_ids | ref_ids
        if not initial_recursive_seed_ids:
            return

        existing_ids = self.paper_repo.get_all_openalex_ids(self.project.id)
        for paper_id in sorted(initial_recursive_seed_ids):
            if paper_id in existing_ids:
                continue
            work = await self._get_work(paper_id)
            if not work:
                continue
            paper = self._work_to_paper(work)
            paper.discovery_method = DiscoveryMethod.SEED
            paper.iteration_added = 0
            self.paper_repo.create(self.project.id, paper)
            existing_ids.add(paper_id)

        # Working set becomes the recursive seed union for iteration 1
        all_papers = self.paper_repo.list_by_project(self.project.id)
        seed_lookup = {p.openalex_id: p for p in all_papers}
        self.working_set = [
            seed_lookup[pid] for pid in sorted(initial_recursive_seed_ids) if pid in seed_lookup
        ]
        self.all_collected = all_papers

    def _run_ref_counter(self, directory: Path) -> dict:
        """Execute ref_counter pipeline and return JSON payload."""
        repo_root = Path(__file__).resolve().parents[3]
        ref_counter_src = repo_root / "reference_counter" / "src"
        if not ref_counter_src.exists():
            return {}

        sys.path.insert(0, str(ref_counter_src))
        try:
            from ref_counter.pipeline import run_pipeline

            # no_resolve=False to obtain source_openalex_ids and resolved references.
            result = run_pipeline(
                directory,
                api_key=self.api_client.identity,
                no_resolve=False,
                min_freq=1,
                weighted=True,
                force_style=None,
                concurrency=5,
                verbose=False,
            )
            return result if isinstance(result, dict) else json.loads(result)
        except Exception:
            return {}
        finally:
            if str(ref_counter_src) in sys.path:
                sys.path.remove(str(ref_counter_src))

    async def _run_iteration(self, iteration_num: int) -> IterationMetrics:
        iteration_id = self.iteration_repo.create(self.project.id, iteration_num)

        current_seed_ids = {p.openalex_id for p in self.working_set}
        existing_ids = self.paper_repo.get_all_openalex_ids(self.project.id)

        backward_counter: Counter[str] = Counter()
        forward_counter: Counter[str] = Counter()

        for seed_id in current_seed_ids:
            refs = await self._get_references(seed_id)
            for ref_id in refs:
                if ref_id not in current_seed_ids:
                    backward_counter[ref_id] += 1

            citers = await self._get_citers(seed_id)
            for citer_id in citers:
                if citer_id not in current_seed_ids:
                    forward_counter[citer_id] += 1

        backward_selected = {pid for pid, cnt in backward_counter.items() if cnt >= 2}
        forward_selected = {pid for pid, cnt in forward_counter.items() if cnt >= 2}
        candidate_union = backward_selected | forward_selected

        new_ids = {pid for pid in candidate_union if pid not in current_seed_ids}
        new_papers: list[Paper] = []

        for paper_id in sorted(new_ids):
            if paper_id in existing_ids:
                continue
            work = await self._get_work(paper_id)
            if not work:
                continue

            paper = self._work_to_paper(work)
            if paper_id in backward_selected and paper_id in forward_selected:
                paper.discovery_method = DiscoveryMethod.RELATED
            elif paper_id in backward_selected:
                paper.discovery_method = DiscoveryMethod.BACKWARD
            else:
                paper.discovery_method = DiscoveryMethod.FORWARD
            paper.iteration_added = iteration_num

            sources = set()
            if paper_id in backward_selected:
                sources.update(
                    [seed for seed in current_seed_ids if paper_id in await self._get_references(seed)]
                )
            if paper_id in forward_selected:
                sources.update(
                    [seed for seed in current_seed_ids if paper_id in await self._get_citers(seed)]
                )
            paper.discovered_from = sorted(sources)

            self.paper_repo.create(self.project.id, paper)
            existing_ids.add(paper_id)
            new_papers.append(paper)

        next_seed_ids = current_seed_ids | {p.openalex_id for p in new_papers}
        all_papers = self.paper_repo.list_by_project(self.project.id)
        lookup = {p.openalex_id: p for p in all_papers}
        self.working_set = [lookup[pid] for pid in sorted(next_seed_ids) if pid in lookup]
        self.all_collected = all_papers

        candidates_count = len(candidate_union)
        papers_before = len(self.all_collected) - len(new_papers)
        papers_after = len(self.all_collected)
        new_count = len(new_papers)
        growth_rate = (new_count / papers_before) if papers_before > 0 else 0.0
        novelty_rate = (new_count / candidates_count) if candidates_count > 0 else 0.0

        metrics = IterationMetrics(
            iteration_number=iteration_num,
            papers_before=papers_before,
            papers_after=papers_after,
            new_papers=new_count,
            growth_rate=growth_rate,
            novelty_rate=novelty_rate,
            forward_found=len(forward_selected),
            backward_found=len(backward_selected),
            author_found=0,
            related_found=0,
        )
        self.iteration_repo.complete(iteration_id, metrics)
        return metrics

    async def _get_work(self, paper_id: str) -> Work | None:
        if paper_id in self._work_cache:
            return self._work_cache[paper_id]
        try:
            work = await self.api_client.get_work(paper_id)
        except Exception:
            work = None
        self._work_cache[paper_id] = work
        return work

    async def _get_references(self, seed_id: str) -> set[str]:
        if seed_id in self._references_cache:
            return self._references_cache[seed_id]
        try:
            response = await self.api_client.get_paper_references(seed_id, limit=200)
            refs = {w.openalex_id for w in response.results if w.openalex_id}
        except Exception:
            refs = set()
        self._references_cache[seed_id] = refs
        return refs

    async def _get_citers(self, seed_id: str) -> set[str]:
        if seed_id in self._citers_cache:
            return self._citers_cache[seed_id]
        try:
            response = await self.api_client.get_paper_citations(seed_id, limit=200)
            citers = {w.openalex_id for w in response.results if w.openalex_id}
        except Exception:
            citers = set()
        self._citers_cache[seed_id] = citers
        return citers

    @staticmethod
    def _work_to_paper(work: Work) -> Paper:
        import uuid

        return Paper(
            id=str(uuid.uuid4()),
            openalex_id=work.openalex_id,
            doi=work.doi,
            title=work.title or "",
            authors=[a.author for a in work.authorships if a.author.display_name],
            publication_year=work.publication_year,
            journal=work.type,
            abstract=work.abstract,
            cited_by_count=work.cited_by_count,
            counts_by_year=work.counts_by_year,
            referenced_works=work.referenced_works,
            score=0.0,
        )

