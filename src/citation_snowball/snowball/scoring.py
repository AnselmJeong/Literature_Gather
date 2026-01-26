"""Scoring algorithm for ranking papers."""
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING

from citation_snowball.core.models import Paper, ScoreBreakdown, ScoringWeights, Work

if TYPE_CHECKING:
    pass


@dataclass
class ScoringContext:
    """Context needed for scoring papers."""

    seed_papers: list[Paper]
    seed_authors: set[str]
    current_year: int
    weights: ScoringWeights
    seed_referenced_works: set[str]  # OpenAlex IDs referenced by seeds


class Scorer:
    """Calculate relevance scores for papers.

    Scores are based on:
    1. Citation velocity (citations per year)
    2. Recent citation activity (last 3 years)
    3. Foundational score (how many seeds cite this paper)
    4. Author overlap with seeds
    5. Recency bonus (newer papers get bonus)
    """

    def __init__(self, weights: ScoringWeights | None = None):
        """Initialize scorer.

        Args:
            weights: Scoring weights (uses defaults if None)
        """
        self.weights = weights or ScoringWeights()

    def calculate_score(
        self, work: Work, context: ScoringContext
    ) -> float:
        """Calculate overall score for a work.

        Args:
            work: OpenAlex Work to score
            context: Scoring context with seed information

        Returns:
            Composite score (0.0 to 1.0+)
        """
        breakdown = self.get_score_breakdown(work, context)
        return breakdown.total

    def get_score_breakdown(
        self, work: Work, context: ScoringContext
    ) -> ScoreBreakdown:
        """Get detailed score breakdown for a work.

        Args:
            work: OpenAlex Work to score
            context: Scoring context with seed information

        Returns:
            ScoreBreakdown with individual component scores
        """
        # 1. Citation Velocity
        citation_velocity = self._calculate_citation_velocity(work, context)

        # 2. Recent Citations
        recent_citations = self._calculate_recent_citations(work, context)

        # 3. Foundational Score
        foundational_score = self._calculate_foundational_score(work, context)

        # 4. Author Overlap
        author_overlap = self._calculate_author_overlap(work, context)

        # 5. Recency Bonus
        recency_bonus = self._calculate_recency_bonus(work, context)

        # Weighted combination
        total = (
            self.weights.citation_velocity * citation_velocity
            + self.weights.recent_citations * recent_citations
            + self.weights.foundational * foundational_score
            + self.weights.author_overlap * author_overlap
            + self.weights.recency * recency_bonus
        )

        return ScoreBreakdown(
            citation_velocity=citation_velocity,
            recent_citations=recent_citations,
            foundational_score=foundational_score,
            author_overlap=author_overlap,
            recency_bonus=recency_bonus,
            total=total,
        )

    def _calculate_citation_velocity(
        self, work: Work, context: ScoringContext
    ) -> float:
        """Calculate citation velocity (citations per year).

        Higher velocity = more rapidly cited paper.

        Args:
            work: OpenAlex Work to score
            context: Scoring context

        Returns:
            Normalized velocity score (0.0 to 1.0)
        """
        if not work.publication_year or work.publication_year >= context.current_year:
            return 0.0

        age = context.current_year - work.publication_year
        if age <= 0:
            return 0.0

        velocity = work.cited_by_count / age

        # Normalize using a reasonable max (e.g., 100 citations/year)
        # This is a heuristic - can be adjusted based on field
        max_expected_velocity = 100.0
        normalized = min(velocity / max_expected_velocity, 1.0)

        return normalized

    def _calculate_recent_citations(
        self, work: Work, context: ScoringContext
    ) -> float:
        """Calculate recent citation activity (last 3 years).

        Args:
            work: OpenAlex Work to score
            context: Scoring context

        Returns:
            Normalized recent citations score (0.0 to 1.0)
        """
        if not work.counts_by_year:
            return 0.0

        # Get last 3 years
        recent_years = [
            context.current_year - i
            for i in range(3)
            if context.current_year - i >= work.publication_year
        ]

        recent_total = 0
        for year_count in work.counts_by_year:
            if year_count.year in recent_years:
                recent_total += year_count.cited_by_count

        # Normalize using a reasonable max (e.g., 100 recent citations)
        max_expected_recent = 100.0
        normalized = min(recent_total / max_expected_recent, 1.0)

        return normalized

    def _calculate_foundational_score(
        self, work: Work, context: ScoringContext
    ) -> float:
        """Calculate foundational score.

        Higher score = more seeds cite this paper (indicates importance).

        Args:
            work: OpenAlex Work to score
            context: Scoring context with seed reference data

        Returns:
            Foundational score (0.0 to 1.0)
        """
        if not context.seed_papers:
            return 0.0

        # Count how many seed papers reference this work
        citing_seed_count = 0

        # Check if this work's OpenAlex ID is in seeds' referenced works
        work_id = work.openalex_id

        # Get all works referenced by seeds
        for seed in context.seed_papers:
            for ref_id in seed.referenced_works:
                if ref_id.replace("https://openalex.org/", "") == work_id:
                    citing_seed_count += 1
                    break

        # Normalize by total seed count
        foundational_score = citing_seed_count / len(context.seed_papers)

        return foundational_score

    def _calculate_author_overlap(
        self, work: Work, context: ScoringContext
    ) -> float:
        """Calculate author overlap with seed papers.

        Higher score = more shared authors with seeds.

        Args:
            work: OpenAlex Work to score
            context: Scoring context with seed authors

        Returns:
            Author overlap score (0.0 to 1.0)
        """
        if not context.seed_authors:
            return 0.0

        if not work.authorships:
            return 0.0

        # Get author OpenAlex IDs from this work
        work_author_ids = {a.author.id for a in work.authorships if a.author.id}

        if not work_author_ids:
            return 0.0

        # Count overlapping authors
        overlap_count = len(work_author_ids & context.seed_authors)

        # Normalize by work author count (Jaccard-like)
        overlap_score = overlap_count / len(work_author_ids)

        return overlap_score

    def _calculate_recency_bonus(
        self, work: Work, context: ScoringContext
    ) -> float:
        """Calculate recency bonus for newer papers.

        Args:
            work: OpenAlex Work to score
            context: Scoring context

        Returns:
            Recency bonus (0.0 to 1.0)
        """
        if not work.publication_year:
            return 0.0

        age = context.current_year - work.publication_year

        if age < 0:
            # Future paper (shouldn't happen)
            return 0.0

        # Linear decay: 1.0 for age 0, 0.0 for age 10+
        decay_period = 10  # years
        recency_bonus = max(0.0, 1.0 - (age / decay_period))

        return recency_bonus


def create_default_context(
    seed_papers: list[Paper], weights: ScoringWeights | None = None
) -> ScoringContext:
    """Create a default scoring context from seed papers.

    Args:
        seed_papers: List of seed papers
        weights: Scoring weights (uses defaults if None)

    Returns:
        ScoringContext with populated seed information
    """
    current_year = datetime.now().year

    # Collect all seed author IDs
    seed_authors: set[str] = set()
    for seed in seed_papers:
        seed_authors.update(seed.author_ids)

    # Collect all works referenced by seeds
    seed_referenced_works: set[str] = set()
    for seed in seed_papers:
        seed_referenced_works.update(
            ref.replace("https://openalex.org/", "") for ref in seed.referenced_works
        )

    return ScoringContext(
        seed_papers=seed_papers,
        seed_authors=seed_authors,
        current_year=current_year,
        weights=weights or ScoringWeights(),
        seed_referenced_works=seed_referenced_works,
    )