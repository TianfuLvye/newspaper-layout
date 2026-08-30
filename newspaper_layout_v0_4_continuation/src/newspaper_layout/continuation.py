from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ContinuationPolicy:
    """
    Central policy for article continuation ("下转").

    The optimizer uses this now when it predicts overflow. A future DOMSplitter /
    ContinuationAllocator should use the same policy, so adding real continuation
    cannot accidentally make splitting cheap again.
    """

    # Raw severity is multiplied by MatchWeights.split.
    first_segment_cost: float = 1.0
    quadratic_cost: float = 1.0
    extra_segment_cost: float = 0.75

    # Additional raw severity when the article has a reasonably good unsplit home
    # elsewhere in the template library.
    avoidable_cost_per_split: float = 3.25

    def severity(self, continuation_count: int) -> float:
        n = max(0, int(continuation_count))
        if n == 0:
            return 0.0
        # n=1 -> 2.0, n=2 -> 5.75, n=3 -> 11.5
        return (
            self.first_segment_cost
            + self.quadratic_cost * (n * n)
            + self.extra_segment_cost * max(0, n - 1)
        )

    def avoidable_severity(self, continuation_count: int) -> float:
        n = max(0, int(continuation_count))
        return self.avoidable_cost_per_split * n
