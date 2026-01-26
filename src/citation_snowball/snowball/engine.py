"""Main snowballing iteration engine."""
import asyncio
from collections import defaultdict
from typing import TYPE_CHECKING

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
from citation_snowball.snowball.filtering import DiscoveryTracker, PaperFilter
from citation_snowball.snowball.saturation import SaturationTracker
from citation_snowball.snowball.scoring import Scorer, create_default_context

if TYPE_CHECKING:
    pass


class SnowballEngine:
    """Main snowballing iteration engine.

    Orchestrates the snowballing process:
    1. For each iteration, expand from working set
    2. Collect candidates from forward, backward, and author sources
    3. Filter and score candidates
    4. Select top N papers
    5. Check saturation
    6. Continue or stop based on configuration
    """

    def __init__(
        self,
        project: Project,
        api_client: OpenAlexClient,
        paper_repo: PaperRepository,
        iteration_repo: IterationRepository,
    ):
        """Initialize snowball engine.

        Args:
            project: Project to run snowballing on
            api_client: OpenAlex API client
            paper_repo: Paper repository
            iteration_repo: Iteration repository
        """
        self.project = project
        self.api_client = api_client
        self.paper_repo = paper_repo
        self.iteration_repo = iteration_repo

        # Components
        self.scorer = Scorer(self.project.config.weights)
        self.filter = PaperFilter(self.project.config)
        self.discovery_tracker = DiscoveryTracker()
        self.saturation_tracker = SaturationTracker(self.project.config)

        # State
        self.working_set: list[Paper] = []
        self.all_collected: list[Paper] = []
        self._stop_requested = False

    async def run(self, progress_callback=None) -> IterationMetrics | None:
        """Run the snowballing process to completion or saturation.

        Args:
            progress_callback: Optional callback for progress updates

        Returns:
            Final iteration metrics, or None if stopped early
        """
        # Initialize with seed papers
        await self._initialize()

        if not self.working_set:
            raise ValueError("No seed papers found")

        iteration_count = 0

        # Run iterations
        while not self._stop_requested:
            iteration_count += 1
            self.project.current_iteration = iteration_count

            # Run single iteration
            metrics = await self._run_iteration(iteration_count)

            # Update tracker
            self.saturation_tracker.add_iteration(metrics)

            # Callback for progress
            if progress_callback:
                await progress_callback(iteration_count, metrics)

            # Check saturation
            from citation_snowball.snowball.saturation import SaturationDetector

            detector = SaturationDetector(self.project.config)
            saturation_result = detector.check(metrics)

            # Update project
            self.project.is_complete = saturation_result.is_saturated
            ProjectRepository(self.paper_repo.db).update(self.project)

            # Stop if saturated
            if saturation_result.is_saturated:
                break

            # Check iteration mode for user interaction
            if self.project.config.iteration_mode == "manual":
                # Wait for user decision (would need CLI integration)
                # For now, just continue
                pass
            elif self.project.config.iteration_mode == "fixed":
                # Fixed iteration mode - stop when max reached
                if iteration_count >= self.project.config.max_iterations:
                    break

        return metrics if self.all_collected else None

    def stop(self) -> None:
        """Request to stop snowballing."""
        self._stop_requested = True

    async def _initialize(self) -> None:
        """Initialize snowballing with seed papers."""
        # Get seed papers from database
        self.working_set = self.paper_repo.list_seeds(self.project.id)
        self.all_collected = self.working_set.copy()

        if not self.working_set:
            raise ValueError("No seed papers found in project")

    async def _run_iteration(self, iteration_num: int) -> IterationMetrics:
        """Run a single snowballing iteration.

        Args:
            iteration_num: Current iteration number

        Returns:
            IterationMetrics for this iteration
        """
        # Start iteration record
        iteration_id = self.iteration_repo.create(self.project.id, iteration_num)

        # Get scoring context
        context = create_default_context(
            self.working_set, self.project.config.weights
        )

        # Collect candidates
        candidates = await self._collect_candidates()

        # Filter candidates
        filtered_candidates = self._filter_candidates(candidates)

        # Score candidates
        scored_candidates = self._score_candidates(filtered_candidates, context)

        # Select top papers
        selected_papers = self._select_papers(scored_candidates)

        # Update working set and collection
        self.working_set = selected_papers
        self.all_collected.extend(selected_papers)

        # Store new papers in database
        for paper in selected_papers:
            # Set discovery info
            method = self.discovery_tracker.get_discovery_method(paper.openalex_id)
            sources = self.discovery_tracker.get_discovery_sources(paper.openalex_id)

            paper.discovery_method = method
            paper.discovered_from = list(sources)
            paper.iteration_added = iteration_num

            self.paper_repo.create(self.project.id, paper)

        # Calculate metrics
        metrics = self._calculate_metrics(iteration_num, candidates, selected_papers)

        # Complete iteration
        self.iteration_repo.complete(iteration_id, metrics)

        return metrics

    async def _collect_candidates(self) -> list[Work]:
        """Collect candidate papers from multiple sources.

        Returns:
            List of candidate works
        """
        candidates_by_source = defaultdict(list)

        # Get existing IDs to avoid duplicates
        existing_ids = self.paper_repo.get_all_openalex_ids(self.project.id)

        # Process each paper in working set
        tasks = []

        for paper in self.working_set:
            # Forward citations
            tasks.append(
                self._collect_forward_citations(
                    paper, candidates_by_source["forward"], existing_ids
                )
            )

            # Backward citations (referenced works)
            tasks.append(
                self._collect_backward_citations(
                    paper, candidates_by_source["backward"], existing_ids
                )
            )

            # Author papers
            tasks.append(
                self._collect_author_papers(
                    paper, candidates_by_source["author"], existing_ids
                )
            )

        # Run all collection tasks
        await asyncio.gather(*tasks, return_exceptions=True)

        # Combine all candidates
        all_candidates = []
        for source, works in candidates_by_source.items():
            all_candidates.extend(works)

        return all_candidates

    async def _collect_forward_citations(
        self,
        paper: Paper,
        candidates: list[Work],
        existing_ids: set[str],
    ) -> None:
        """Collect papers that cite the given paper.

        Args:
            paper: Source paper
            candidates: List to append found works to
            existing_ids: Already collected IDs to skip
        """
        try:
            response = await self.api_client.get_citing_works(
                paper.openalex_id, per_page=50
            )

            for work in response.results:
                if work.openalex_id not in existing_ids:
                    candidates.append(work)
                    self.discovery_tracker.add_discovery(
                        work.openalex_id, DiscoveryMethod.FORWARD, {paper.openalex_id}
                    )

        except Exception as e:
            # Log error but continue
            pass

    async def _collect_backward_citations(
        self,
        paper: Paper,
        candidates: list[Work],
        existing_ids: set[str],
    ) -> None:
        """Collect papers referenced by the given paper.

        Args:
            paper: Source paper
            candidates: List to append found works to
            existing_ids: Already collected IDs to skip
        """
        try:
            # Get full work to access referenced_works
            work = await self.api_client.get_work(paper.openalex_id)

            if work.referenced_works:
                # Batch fetch referenced works
                works = await self.api_client.get_works_batch(work.referenced_works[:50])

                for ref_work in works:
                    if ref_work.openalex_id not in existing_ids:
                        candidates.append(ref_work)
                        self.discovery_tracker.add_discovery(
                            ref_work.openalex_id,
                            DiscoveryMethod.BACKWARD,
                            {paper.openalex_id},
                        )

        except Exception as e:
            # Log error but continue
            pass

    async def _collect_author_papers(
        self,
        paper: Paper,
        candidates: list[Work],
        existing_ids: set[str],
    ) -> None:
        """Collect recent papers by authors of the given paper.

        Args:
            paper: Source paper
            candidates: List to append found works to
            existing_ids: Already collected IDs to skip
        """
        try:
            # Limit to first few authors to avoid too many requests
            author_ids = paper.author_ids[:5]

            for author_id in author_ids:
                response = await self.api_client.get_author_works(
                    author_id,
                    from_year=max(
                        2000, self.project.config.min_year or 2000
                    ),
                    per_page=20,
                )

                for work in response.results:
                    if work.openalex_id not in existing_ids:
                        candidates.append(work)
                        self.discovery_tracker.add_discovery(
                            work.openalex_id,
                            DiscoveryMethod.AUTHOR,
                            {paper.openalex_id},
                        )

        except Exception as e:
            # Log error but continue
            pass

    def _filter_candidates(self, candidates: list[Work]) -> list[Work]:
        """Filter candidates based on project criteria.

        Args:
            candidates: List of candidate works

        Returns:
            Filtered list of works
        """
        filtered = []
        existing_ids = self.paper_repo.get_all_openalex_ids(self.project.id)

        for work in candidates:
            # Check inclusion criteria
            if not self.filter.should_include(work):
                continue

            # Check exclusion criteria
            should_exclude, _ = self.filter.should_exclude(work, existing_ids)
            if should_exclude:
                continue

            filtered.append(work)

        return filtered

    def _score_candidates(
        self, candidates: list[Work], context
    ) -> list[tuple[Work, float]]:
        """Score all candidates.

        Args:
            candidates: List of candidate works
            context: Scoring context

        Returns:
            List of (work, score) tuples sorted by score (descending)
        """
        scored = []

        for work in candidates:
            score = self.scorer.calculate_score(work, context)
            scored.append((work, score))

        # Sort by score (descending)
        scored.sort(key=lambda x: x[1], reverse=True)

        return scored

    def _select_papers(
        self, scored_candidates: list[tuple[Work, float]]
    ) -> list[Paper]:
        """Select top papers to add to collection.

        Args:
            scored_candidates: List of (work, score) tuples

        Returns:
            List of selected Paper objects
        """
        # Get top N papers
        top_count = min(
            len(scored_candidates), self.project.config.papers_per_iteration
        )

        selected = []
        for work, score in scored_candidates[:top_count]:
            # Convert Work to Paper
            paper = Paper(
                openalex_id=work.openalex_id,
                doi=work.doi,
                title=work.title or "",
                authors=[
                    a.author for a in work.authorships if a.author.display_name
                ],
                publication_year=work.publication_year,
                journal=work.type,
                abstract=work.abstract,
                cited_by_count=work.cited_by_count,
                counts_by_year=work.counts_by_year,
                referenced_works=work.referenced_works,
                score=score,
            )
            selected.append(paper)

        return selected

    def _calculate_metrics(
        self,
        iteration_num: int,
        candidates: list[Work],
        selected_papers: list[Paper],
    ) -> IterationMetrics:
        """Calculate iteration metrics.

        Args:
            iteration_num: Current iteration number
            candidates: All candidates found
            selected_papers: Papers selected for collection

        Returns:
            IterationMetrics for this iteration
        """
        papers_before = len(self.all_collected) - len(selected_papers)
        papers_after = len(self.all_collected)
        new_papers = len(selected_papers)

        growth_rate = new_papers / papers_before if papers_before > 0 else 0.0
        novelty_rate = new_papers / len(candidates) if candidates else 0.0

        return IterationMetrics(
            iteration_number=iteration_num,
            papers_before=papers_before,
            papers_after=papers_after,
            new_papers=new_papers,
            growth_rate=growth_rate,
            novelty_rate=novelty_rate,
            # Source counts would need to be tracked during collection
            forward_found=0,
            backward_found=0,
            author_found=0,
            related_found=0,
        )