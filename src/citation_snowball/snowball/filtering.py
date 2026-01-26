"""Paper filtering for candidate selection."""
from citation_snowball.core.models import DiscoveryMethod, ProjectConfig, Work


class PaperFilter:
    """Filter candidate papers based on criteria.

    Applies inclusion and exclusion filters to determine which papers
    should be considered for addition to the collection.
    """

    def __init__(self, config: ProjectConfig):
        """Initialize paper filter.

        Args:
            config: Project configuration with filter criteria
        """
        self.config = config

    def should_include(self, work: Work) -> bool:
        """Check if a work meets inclusion criteria.

        Args:
            work: OpenAlex Work to check

        Returns:
            True if work should be included, False otherwise
        """
        # Check publication year range
        if work.publication_year:
            if self.config.min_year and work.publication_year < self.config.min_year:
                return False
            if self.config.max_year and work.publication_year > self.config.max_year:
                return False

        # Check document type
        if not self._is_valid_type(work):
            return False

        # Check language
        if not self._is_valid_language(work):
            return False

        # Check minimum citations
        if work.cited_by_count < self.config.min_citations:
            return False

        # Check if retracted
        if work.is_retracted:
            return False

        return True

    def should_exclude(
        self, work: Work, existing_ids: set[str]
    ) -> tuple[bool, str | None]:
        """Check if a work should be excluded.

        Args:
            work: OpenAlex Work to check
            existing_ids: Set of OpenAlex IDs already in collection

        Returns:
            Tuple of (should_exclude: bool, reason: str | None)
        """
        # Check if already in collection
        work_id = work.openalex_id
        if work_id in existing_ids:
            return True, "Already in collection"

        return False, None

    def _is_valid_type(self, work: Work) -> bool:
        """Check if work type is valid.

        Args:
            work: OpenAlex Work to check

        Returns:
            True if type is valid, False otherwise
        """
        if not work.type:
            return False

        # Valid document types
        valid_types = {
            "journal-article",
            "article",
            "review",
            "preprint",
            "posted-content",
            "book",
            "book-chapter",
        }

        # Check against valid types
        work_type = work.type.lower().replace("-", "_")
        if self.config.include_preprints:
            return work_type in {
                t.replace("-", "_") for t in valid_types
            }
        else:
            # Exclude preprints if not allowed
            exclude_types = {"preprint", "posted-content"}
            return (
                work_type in {t.replace("-", "_") for t in valid_types}
                and work_type not in exclude_types
            )

    def _is_valid_language(self, work: Work) -> bool:
        """Check if work language is valid.

        Args:
            work: OpenAlex Work to check

        Returns:
            True if language is valid, False otherwise
        """
        # If no language specified, include it (better to include than exclude)
        if not work.language:
            return True

        # Check against configured languages
        return work.language.lower() == self.config.language.lower()


class DiscoveryTracker:
    """Track how papers were discovered during snowballing."""

    def __init__(self):
        """Initialize discovery tracker."""
        self._discoveries: dict[str, tuple[DiscoveryMethod, set[str]]] = {}

    def add_discovery(
        self, work_id: str, method: DiscoveryMethod, source_ids: set[str]
    ) -> None:
        """Record how a work was discovered.

        Args:
            work_id: OpenAlex ID of discovered work
            method: How it was discovered (forward, backward, author)
            source_ids: Work IDs that led to this discovery
        """
        if work_id in self._discoveries:
            # Merge with existing discovery
            existing_method, existing_sources = self._discoveries[work_id]
            # Prefer more specific methods: author > forward > backward
            priority = {
                DiscoveryMethod.AUTHOR: 3,
                DiscoveryMethod.FORWARD: 2,
                DiscoveryMethod.BACKWARD: 1,
                DiscoveryMethod.RELATED: 1,
            }
            if priority.get(method, 0) > priority.get(existing_method, 0):
                self._discoveries[work_id] = (method, source_ids)
            else:
                existing_sources.update(source_ids)
        else:
            self._discoveries[work_id] = (method, source_ids)

    def get_discovery_method(self, work_id: str) -> DiscoveryMethod:
        """Get how a work was discovered.

        Args:
            work_id: OpenAlex ID of work

        Returns:
            DiscoveryMethod used
        """
        if work_id in self._discoveries:
            return self._discoveries[work_id][0]
        return DiscoveryMethod.SEED

    def get_discovery_sources(self, work_id: str) -> set[str]:
        """Get source work IDs that led to this discovery.

        Args:
            work_id: OpenAlex ID of work

        Returns:
            Set of source work IDs
        """
        if work_id in self._discoveries:
            return self._discoveries[work_id][1]
        return set()

    def clear(self) -> None:
        """Clear all discovery records."""
        self._discoveries.clear()

    def get_all_discoveries(self) -> dict[str, tuple[DiscoveryMethod, set[str]]]:
        """Get all discovery records.

        Returns:
            Dictionary mapping work IDs to (method, sources) tuples
        """
        return self._discoveries.copy()