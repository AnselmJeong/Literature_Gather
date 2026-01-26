"""Saturation detection for determining when to stop snowballing."""
from dataclasses import dataclass

from citation_snowball.core.models import IterationMetrics, ProjectConfig


@dataclass
class SaturationResult:
    """Result of saturation check."""

    is_saturated: bool
    reason: str | None
    confidence: float  # 0.0 to 1.0


class SaturationDetector:
    """Detects when snowballing has reached diminishing returns.

    Uses multiple signals:
    1. Growth rate below threshold
    2. Novelty rate below threshold
    3. Maximum iterations reached
    4. Maximum papers reached
    """

    def __init__(self, config: ProjectConfig):
        """Initialize saturation detector.

        Args:
            config: Project configuration with thresholds
        """
        self.config = config

    def check(self, metrics: IterationMetrics) -> SaturationResult:
        """Check if saturation has been reached.

        Args:
            metrics: Current iteration metrics

        Returns:
            SaturationResult with decision and explanation
        """
        # Check 1: No new papers added (most definitive)
        if metrics.new_papers == 0:
            return SaturationResult(
                is_saturated=True,
                reason="No new papers added this iteration",
                confidence=1.0,
            )

        # Check 2: Maximum iterations reached
        if metrics.iteration_number >= self.config.max_iterations:
            return SaturationResult(
                is_saturated=True,
                reason=f"Maximum iterations ({self.config.max_iterations}) reached",
                confidence=1.0,
            )

        # Check 3: Growth rate below threshold
        if metrics.growth_rate < self.config.growth_threshold:
            return SaturationResult(
                is_saturated=True,
                reason=f"Growth rate {metrics.growth_rate:.1%} below threshold {self.config.growth_threshold:.1%}",
                confidence=0.8 + (1.0 - metrics.growth_rate / self.config.growth_threshold) * 0.2,
            )

        # Check 4: Novelty rate below threshold
        if metrics.novelty_rate < self.config.novelty_threshold:
            return SaturationResult(
                is_saturated=True,
                reason=f"Novelty rate {metrics.novelty_rate:.1%} below threshold {self.config.novelty_threshold:.1%}",
                confidence=0.9,
            )

        # Not saturated
        return SaturationResult(
            is_saturated=False,
            reason=None,
            confidence=0.0,
        )

    def get_saturation_progress(self, metrics: IterationMetrics) -> float:
        """Estimate overall progress toward saturation.

        Args:
            metrics: Current iteration metrics

        Returns:
            Progress estimate (0.0 to 1.0)
        """
        progress = 0.0

        # Iteration progress (max 30% of total)
        iteration_progress = metrics.iteration_number / self.config.max_iterations
        progress += iteration_progress * 0.3

        # Growth-based progress (max 40% of total)
        if metrics.growth_rate < self.config.growth_threshold:
            growth_progress = 1.0 - (
                metrics.growth_rate / self.config.growth_threshold
            )
        else:
            # Some progress even above threshold
            growth_progress = 0.5 - (
                metrics.growth_rate - self.config.growth_threshold
            ) * 2
            growth_progress = max(0.0, min(0.5, growth_progress))
        progress += growth_progress * 0.4

        # Novelty-based progress (max 30% of total)
        if metrics.novelty_rate < self.config.novelty_threshold:
            novelty_progress = 1.0 - (
                metrics.novelty_rate / self.config.novelty_threshold
            )
        else:
            # Some progress even above threshold
            novelty_progress = 0.5 - (
                metrics.novelty_rate - self.config.novelty_threshold
            ) * 2
            novelty_progress = max(0.0, min(0.5, novelty_progress))
        progress += novelty_progress * 0.3

        return min(progress, 1.0)


class SaturationTracker:
    """Tracks saturation across multiple iterations."""

    def __init__(self, config: ProjectConfig):
        """Initialize saturation tracker.

        Args:
            config: Project configuration
        """
        self.config = config
        self.history: list[IterationMetrics] = []

    def add_iteration(self, metrics: IterationMetrics) -> None:
        """Add iteration metrics to history.

        Args:
            metrics: Iteration metrics to add
        """
        self.history.append(metrics)

    def check(self) -> SaturationResult:
        """Check if overall saturation has been reached.

        Considers trends across multiple iterations, not just current state.

        Returns:
            SaturationResult with decision
        """
        if not self.history:
            return SaturationResult(
                is_saturated=False, reason=None, confidence=0.0
            )

        latest = self.history[-1]
        detector = SaturationDetector(self.config)

        # Check basic saturation conditions
        basic_result = detector.check(latest)
        if basic_result.is_saturated:
            return basic_result

        # Check for declining trends
        if len(self.history) >= 3:
            # Check if growth rate is declining
            growth_rates = [m.growth_rate for m in self.history[-3:]]
            if all(
                growth_rates[i] >= growth_rates[i + 1]
                for i in range(len(growth_rates) - 1)
            ):
                # Growth is declining - nearing saturation
                return SaturationResult(
                    is_saturated=False,
                    reason="Growth rate declining (consider stopping soon)",
                    confidence=0.6,
                )

        # Check novelty trend
        if len(self.history) >= 3:
            novelty_rates = [m.novelty_rate for m in self.history[-3:]]
            if all(
                novelty_rates[i] >= novelty_rates[i + 1]
                for i in range(len(novelty_rates) - 1)
            ):
                return SaturationResult(
                    is_saturated=False,
                    reason="Novelty rate declining (consider stopping soon)",
                    confidence=0.6,
                )

        # Not saturated
        return SaturationResult(
            is_saturated=False,
            reason=None,
            confidence=0.0,
        )

    def get_summary(self) -> dict:
        """Get summary of saturation tracking.

        Returns:
            Dictionary with summary statistics
        """
        if not self.history:
            return {
                "iterations": 0,
                "total_papers": 0,
                "avg_growth_rate": 0.0,
                "avg_novelty_rate": 0.0,
                "trend": "no_data",
            }

        latest = self.history[-1]
        avg_growth = sum(m.growth_rate for m in self.history) / len(self.history)
        avg_novelty = sum(m.novelty_rate for m in self.history) / len(self.history)

        # Determine trend
        if len(self.history) < 3:
            trend = "insufficient_data"
        else:
            growth_trend = self._get_trend([m.growth_rate for m in self.history[-3:]])
            novelty_trend = self._get_trend(
                [m.novelty_rate for m in self.history[-3:]]
            )
            if growth_trend == "declining" and novelty_trend == "declining":
                trend = "declining"
            elif growth_trend == "stable" and novelty_trend == "stable":
                trend = "stable"
            else:
                trend = "growing"

        return {
            "iterations": len(self.history),
            "total_papers": latest.papers_after,
            "avg_growth_rate": avg_growth,
            "avg_novelty_rate": avg_novelty,
            "trend": trend,
        }

    def _get_trend(self, values: list[float]) -> str:
        """Get trend direction from values.

        Args:
            values: List of values to analyze

        Returns:
            "declining", "stable", or "growing"
        """
        if len(values) < 2:
            return "stable"

        changes = [
            values[i + 1] - values[i] for i in range(len(values) - 1)
        ]

        avg_change = sum(changes) / len(changes)

        if avg_change < -0.01:
            return "declining"
        elif avg_change > 0.01:
            return "growing"
        else:
            return "stable"