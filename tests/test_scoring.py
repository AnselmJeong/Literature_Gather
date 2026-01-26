"""Tests for scoring algorithm."""
from citation_snowball.core.models import (
    AuthorInfo,
    DiscoveryMethod,
    Paper,
    ScoreBreakdown,
    ScoringWeights,
    YearCount,
    Work,
    WorkIds,
)
from citation_snowball.snowball.scoring import Scorer, ScoringContext, create_default_context


def test_scorer_initialization():
    """Test scorer can be initialized."""
    weights = ScoringWeights()
    scorer = Scorer(weights)
    assert scorer.weights == weights


def test_scorer_default_weights():
    """Test scorer with default weights."""
    scorer = Scorer()
    assert scorer.weights.citation_velocity == 0.25
    assert scorer.weights.recent_citations == 0.20
    assert scorer.weights.foundational == 0.25
    assert scorer.weights.author_overlap == 0.15
    assert scorer.weights.recency == 0.15


def test_calculate_score_basic():
    """Test basic score calculation."""
    scorer = Scorer()

    # Create a work with some citations
    work = Work(
        id="https://openalex.org/W123",
        doi="10.1234/test",
        title="Test Paper",
        publication_year=2020,
        cited_by_count=100,
        counts_by_year=[
            YearCount(year=2021, cited_by_count=30),
            YearCount(year=2022, cited_by_count=40),
            YearCount(year=2023, cited_by_count=30),
        ],
        authorships=[
            {
                "author": AuthorInfo(id="A1", display_name="Test Author", orcid=None),
                "author_position": "first",
                "is_corresponding": True,
                "raw_affiliation_strings": [],
                "institutions": [],
            }
        ],
    )

    # Create context with seeds
    seed_author = AuthorInfo(id="A2", display_name="Seed Author", orcid=None)
    seed_paper = Paper(
        id="seed1",
        openalex_id="W456",
        doi="10.1234/seed",
        title="Seed Paper",
        authors=[seed_author],
        publication_year=2019,
        cited_by_count=50,
        referenced_works=["W123"],  # This work is referenced
        discovery_method=DiscoveryMethod.SEED,
    )

    context = create_default_context([seed_paper])

    # Calculate score
    score = scorer.calculate_score(work, context)

    # Score should be positive
    assert score >= 0


def test_score_breakdown():
    """Test score breakdown returns all components."""
    scorer = Scorer()

    work = Work(
        id="https://openalex.org/W123",
        doi="10.1234/test",
        title="Test Paper",
        publication_year=2020,
        cited_by_count=100,
        counts_by_year=[
            YearCount(year=2021, cited_by_count=30),
            YearCount(year=2022, cited_by_count=40),
            YearCount(year=2023, cited_by_count=30),
        ],
        authorships=[
            {
                "author": AuthorInfo(id="A1", display_name="Test Author", orcid=None),
                "author_position": "first",
                "is_corresponding": True,
                "raw_affiliation_strings": [],
                "institutions": [],
            }
        ],
    )

    seed_author = AuthorInfo(id="A2", display_name="Seed Author", orcid=None)
    seed_paper = Paper(
        id="seed1",
        openalex_id="W456",
        doi="10.1234/seed",
        title="Seed Paper",
        authors=[seed_author],
        publication_year=2019,
        cited_by_count=50,
        referenced_works=["W123"],
        discovery_method=DiscoveryMethod.SEED,
    )

    context = create_default_context([seed_paper])
    breakdown = scorer.get_score_breakdown(work, context)

    # All components should be present
    assert isinstance(breakdown, ScoreBreakdown)
    assert breakdown.citation_velocity >= 0
    assert breakdown.recent_citations >= 0
    assert breakdown.foundational_score >= 0
    assert breakdown.author_overlap >= 0
    assert breakdown.recency_bonus >= 0
    assert breakdown.total >= 0


def test_create_default_context():
    """Test default context creation."""
    seed_author = AuthorInfo(id="A1", display_name="Author", orcid=None)
    seed_paper = Paper(
        id="seed1",
        openalex_id="W123",
        doi="10.1234/seed",
        title="Seed Paper",
        authors=[seed_author],
        publication_year=2020,
        cited_by_count=50,
        referenced_works=["W456"],
        discovery_method=DiscoveryMethod.SEED,
    )

    context = create_default_context([seed_paper])

    assert context.seed_papers == [seed_paper]
    assert "A1" in context.seed_authors
    assert context.current_year >= 2020
    assert isinstance(context.weights, ScoringWeights)