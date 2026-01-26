"""Tests for saturation detection."""
from citation_snowball.core.models import IterationMetrics, ProjectConfig
from citation_snowball.snowball.saturation import SaturationDetector, SaturationTracker, SaturationResult


def test_saturation_detector_initialization():
    """Test detector can be initialized."""
    config = ProjectConfig()
    detector = SaturationDetector(config)
    assert detector.config == config


def test_saturation_below_growth_threshold():
    """Test saturation detection when growth rate below threshold."""
    config = ProjectConfig(growth_threshold=0.05)
    detector = SaturationDetector(config)

    metrics = IterationMetrics(
        iteration_number=1,
        papers_before=100,
        papers_after=102,
        new_papers=2,
        growth_rate=0.02,  # Below 0.05 threshold
        novelty_rate=0.15,
    )

    result = detector.check(metrics)
    assert result.is_saturated is True
    assert "growth rate" in result.reason.lower()


def test_saturation_below_novelty_threshold():
    """Test saturation detection when novelty rate below threshold."""
    config = ProjectConfig(novelty_threshold=0.10)
    detector = SaturationDetector(config)

    metrics = IterationMetrics(
        iteration_number=1,
        papers_before=100,
        papers_after=105,
        new_papers=5,
        growth_rate=0.05,
        novelty_rate=0.05,  # Below 0.10 threshold
    )

    result = detector.check(metrics)
    assert result.is_saturated is True
    assert "novelty" in result.reason.lower()


def test_saturation_max_iterations():
    """Test saturation detection when max iterations reached."""
    config = ProjectConfig(max_iterations=3)
    detector = SaturationDetector(config)

    metrics = IterationMetrics(
        iteration_number=3,  # Max iterations
        papers_before=100,
        papers_after=120,
        new_papers=20,
        growth_rate=0.20,
        novelty_rate=0.30,
    )

    result = detector.check(metrics)
    assert result.is_saturated is True
    assert "maximum iterations" in result.reason.lower()


def test_saturation_no_new_papers():
    """Test saturation detection when no new papers added."""
    config = ProjectConfig()
    detector = SaturationDetector(config)

    metrics = IterationMetrics(
        iteration_number=1,
        papers_before=100,
        papers_after=100,
        new_papers=0,  # No new papers
        growth_rate=0.0,
        novelty_rate=0.0,
    )

    result = detector.check(metrics)
    assert result.is_saturated is True
    assert "no new papers" in result.reason.lower()


def test_saturation_not_saturated():
    """Test that paper is not saturated when conditions are met."""
    config = ProjectConfig(
        growth_threshold=0.05,
        novelty_threshold=0.10,
        max_iterations=5,
    )
    detector = SaturationDetector(config)

    metrics = IterationMetrics(
        iteration_number=1,
        papers_before=100,
        papers_after=115,
        new_papers=15,
        growth_rate=0.15,  # Above threshold
        novelty_rate=0.20,  # Above threshold
    )

    result = detector.check(metrics)
    assert result.is_saturated is False
    assert result.reason is None
    assert result.confidence == 0.0


def test_saturation_tracker():
    """Test saturation tracker across multiple iterations."""
    config = ProjectConfig()
    tracker = SaturationTracker(config)

    # Add first iteration
    metrics1 = IterationMetrics(
        iteration_number=1,
        papers_before=10,
        papers_after=20,
        new_papers=10,
        growth_rate=1.0,
        novelty_rate=0.5,
    )
    tracker.add_iteration(metrics1)

    # Add second iteration
    metrics2 = IterationMetrics(
        iteration_number=2,
        papers_before=20,
        papers_after=30,
        new_papers=10,
        growth_rate=0.5,
        novelty_rate=0.4,
    )
    tracker.add_iteration(metrics2)

    # Check summary
    summary = tracker.get_summary()
    assert summary["iterations"] == 2
    assert summary["total_papers"] == 30


def test_saturation_progress():
    """Test saturation progress calculation."""
    config = ProjectConfig(
        growth_threshold=0.05,
        novelty_threshold=0.10,
        max_iterations=5,
    )
    detector = SaturationDetector(config)

    # Low growth rate - should be near saturation
    metrics = IterationMetrics(
        iteration_number=3,
        papers_before=100,
        papers_after=101,
        new_papers=1,
        growth_rate=0.01,  # Very low
        novelty_rate=0.20,
    )

    progress = detector.get_saturation_progress(metrics)
    # Should be high due to growth below threshold
    assert progress > 0.3