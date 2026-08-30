from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import math
from typing import Iterable

from .matching import SlotMatcher
from .models import Article, LayoutPlan, PageAssignment, SlotScore, Template


@dataclass(frozen=True)
class OptimizerConfig:
    beam_width: int = 8
    template_branching: int = 10
    article_shortlist: int = 14
    max_pages: int = 24

    early_long_article_penalty: float = 5.0
    early_report_penalty: float = 8.0

    # Density policy: an empty or visibly underfilled page should be expensive.
    empty_slot_penalty: float = 140.0
    # Targets are absolute content-area utilization, not merely "filled fraction
    # of existing story slots". This also catches templates that leave too much of
    # the physical page unused. Front/special pages reserve more furniture space.
    target_page_utilization: float = 0.90
    front_page_utilization_target: float = 0.70
    special_page_utilization_target: float = 0.80
    page_whitespace_penalty: float = 700.0
    severe_whitespace_penalty: float = 1400.0
    severe_whitespace_threshold: float = 0.30
    page_open_penalty: float = 35.0



@dataclass
class _BeamState:
    remaining_ids: tuple[str, ...]
    pages: list[PageAssignment]
    total_cost: float


class LayoutOptimizer:
    """
    V0.3 global planner with strong density and continuation policy.

    Strategy:
    - Beam search across page-template choices.
    - For each page/template, solve a minimum-cost unique assignment using bitmask DP.
    - Candidate articles are shortlisted per slot to keep the DP small.

    This is intentionally deterministic and dependency-free. A future CP-SAT backend
    can implement the same public API.
    """

    def __init__(
        self,
        matcher: SlotMatcher | None = None,
        config: OptimizerConfig | None = None,
    ):
        self.matcher = matcher or SlotMatcher()
        self.config = config or OptimizerConfig()

    def optimize(
        self,
        articles: list[Article],
        templates: list[Template],
        *,
        page_type: str | None = None,
    ) -> LayoutPlan:
        if not articles:
            return LayoutPlan([], 0.0, [])
        if not templates:
            return LayoutPlan([], math.inf, [a.id for a in articles])

        article_by_id = {a.id: a for a in articles}
        if len(article_by_id) != len(articles):
            raise ValueError("Article ids must be unique")

        usable_templates = [
            t for t in templates
            if page_type is None or t.page.type == page_type
        ]
        if not usable_templates:
            usable_templates = templates[:]

        # Prefer template sizes that are plausible for the remaining article count.
        usable_templates = sorted(
            usable_templates,
            key=lambda t: (-t.personal_rating, -len(t.stories), t.template_id)
        )

        initial = _BeamState(
            remaining_ids=tuple(a.id for a in articles),
            pages=[],
            total_cost=0.0,
        )
        beam = [initial]
        completed: list[_BeamState] = []

        estimated_pages = self._estimate_page_count(articles, usable_templates)

        for page_index in range(self.config.max_pages):
            next_states: list[_BeamState] = []
            for state in beam:
                if not state.remaining_ids:
                    completed.append(state)
                    continue

                remaining = [article_by_id[x] for x in state.remaining_ids]
                template_candidates = self._template_candidates(
                    usable_templates,
                    len(remaining),
                )

                for template in template_candidates:
                    assignment = self._best_page_assignment(
                        remaining,
                        template,
                        page_index=page_index,
                        estimated_pages=estimated_pages,
                    )
                    if assignment is None:
                        continue

                    assigned_ids = {x.article_id for x in assignment.assignments}
                    if not assigned_ids:
                        continue

                    new_remaining = tuple(
                        x for x in state.remaining_ids if x not in assigned_ids
                    )
                    next_states.append(
                        _BeamState(
                            remaining_ids=new_remaining,
                            pages=state.pages + [assignment],
                            total_cost=state.total_cost + assignment.total_cost,
                        )
                    )

            if completed:
                # Still allow another layer if there are competitive incomplete states,
                # then prune by normalized score.
                pass
            if not next_states:
                break

            next_states.sort(
                key=lambda s: (
                    s.total_cost + len(s.remaining_ids) * 50.0,
                    len(s.remaining_ids),
                    len(s.pages),
                )
            )
            beam = next_states[: self.config.beam_width]

            if all(not s.remaining_ids for s in beam):
                completed.extend(beam)
                break

        candidates = completed or beam
        if not candidates:
            return LayoutPlan([], math.inf, [a.id for a in articles])

        best = min(
            candidates,
            key=lambda s: s.total_cost + len(s.remaining_ids) * 1000.0,
        )
        return LayoutPlan(
            pages=best.pages,
            total_cost=best.total_cost + len(best.remaining_ids) * 1000.0,
            unassigned_article_ids=list(best.remaining_ids),
        )

    def _template_candidates(
        self,
        templates: list[Template],
        remaining_count: int,
    ) -> list[Template]:
        ranked = sorted(
            templates,
            key=lambda t: (
                abs(min(len(t.stories), remaining_count) - len(t.stories)),
                -t.personal_rating,
                t.template_id,
            ),
        )
        return ranked[: self.config.template_branching]

    def _best_page_assignment(
        self,
        articles: list[Article],
        template: Template,
        *,
        page_index: int,
        estimated_pages: int,
    ) -> PageAssignment | None:
        slot_count = len(template.stories)
        if slot_count == 0 or not articles:
            return None

        # If fewer articles remain than slots, V1 leaves unused slots with a penalty.
        use_slots = template.stories[: min(slot_count, len(articles))]

        scored_per_slot: list[list[tuple[Article, SlotScore]]] = []
        union_ids: set[str] = set()

        per_slot_limit = max(
            4,
            min(
                self.config.article_shortlist,
                max(4, self.config.article_shortlist // max(1, len(use_slots)) + 5),
            ),
        )

        for slot in use_slots:
            scored = [
                (a, self.matcher.score(a, template, slot))
                for a in articles
            ]
            scored.sort(key=lambda pair: pair[1].total)
            chosen = scored[:per_slot_limit]
            scored_per_slot.append(chosen)
            union_ids.update(a.id for a, _ in chosen)

        # Bound DP complexity.
        shortlist_articles = [a for a in articles if a.id in union_ids]
        if len(shortlist_articles) > self.config.article_shortlist:
            # Aggregate article quality across slots, then keep the best global candidates.
            agg = []
            for a in shortlist_articles:
                best_score = math.inf
                for slot in use_slots:
                    best_score = min(best_score, self.matcher.score(a, template, slot).total)
                agg.append((best_score, a))
            agg.sort(key=lambda x: x[0])
            shortlist_articles = [a for _, a in agg[: self.config.article_shortlist]]

        if len(shortlist_articles) < len(use_slots):
            # Ensure enough articles to fill all active slots.
            existing = {a.id for a in shortlist_articles}
            for a in articles:
                if a.id not in existing:
                    shortlist_articles.append(a)
                    existing.add(a.id)
                if len(shortlist_articles) >= len(use_slots):
                    break

        article_index = {a.id: i for i, a in enumerate(shortlist_articles)}
        score_matrix: list[list[SlotScore]] = []
        for slot in use_slots:
            row = [self.matcher.score(a, template, slot) for a in shortlist_articles]
            score_matrix.append(row)

        # "Unnecessary continuation" is contextual to this page/template.
        # If an article fits unsplit in another active slot on the same page,
        # assigning it to an overflowing slot gets an extra cost inside the DP,
        # allowing the solver to swap articles rather than blindly opening a new page.
        has_unsplit_home = [
            any(row[ai].predicted_splits == 0 for row in score_matrix)
            for ai in range(len(shortlist_articles))
        ]

        def avoidable_split_extra(ai: int, score: SlotScore) -> float:
            if score.predicted_splits <= 0 or not has_unsplit_home[ai]:
                return 0.0
            return (
                self.matcher.weights.split
                * self.matcher.continuation_policy.avoidable_severity(
                    score.predicted_splits
                )
            )

        @lru_cache(maxsize=None)
        def dp(slot_idx: int, used_mask: int):
            if slot_idx == len(use_slots):
                return 0.0, ()
            best_cost = math.inf
            best_choice = ()
            for ai, article in enumerate(shortlist_articles):
                if used_mask & (1 << ai):
                    continue
                score = score_matrix[slot_idx][ai]
                tail_cost, tail_choice = dp(slot_idx + 1, used_mask | (1 << ai))
                cost = score.total + avoidable_split_extra(ai, score) + tail_cost
                if cost < best_cost:
                    best_cost = cost
                    best_choice = (ai,) + tail_choice
            return best_cost, best_choice

        assignment_cost, choices = dp(0, 0)
        if not choices:
            return None

        assignments = [
            score_matrix[slot_idx][ai]
            for slot_idx, ai in enumerate(choices)
        ]

        template_cost = self.matcher.template_prior_cost(template)
        unused_slots = max(0, slot_count - len(assignments))
        template_cost += unused_slots * self.config.empty_slot_penalty

        assigned_articles = [
            shortlist_articles[ai]
            for ai in choices
        ]
        order_cost = sum(
            self._order_cost(a, page_index, estimated_pages)
            for a in assigned_articles
        )

        # Page-level density penalty. Slot-local fit costs alone are not enough:
        # a collection of merely "acceptable" underfilled slots can still produce
        # an obviously empty newspaper page.
        whitespace_cost, utilization = self._page_whitespace_cost(
            template,
            assignments,
        )

        # Diagnostic portion of the DP cost attributable specifically to avoidable
        # splits. The base continuation cost is already inside each SlotScore.
        continuation_cost = sum(
            avoidable_split_extra(ai, score_matrix[slot_idx][ai])
            for slot_idx, ai in enumerate(choices)
        )

        # The DP minimized score.total + avoidable_split_extra. Recompute the base
        # assignment part explicitly so total_cost does not double-count.
        assignment_cost = sum(score.total for score in assignments)

        page_open_cost = self.config.page_open_penalty

        return PageAssignment(
            template_id=template.template_id,
            page_index=page_index,
            assignments=assignments,
            template_cost=template_cost,
            order_cost=order_cost,
            whitespace_cost=whitespace_cost,
            continuation_cost=continuation_cost,
            page_open_cost=page_open_cost,
            utilization=utilization,
            total_cost=(
                assignment_cost
                + template_cost
                + order_cost
                + whitespace_cost
                + continuation_cost
                + page_open_cost
            ),
        )


    def _page_whitespace_cost(
        self,
        template: Template,
        assignments: list[SlotScore],
    ) -> tuple[float, float]:
        """
        Return (cost, utilization).

        Utilization is area-weighted over the template's story slots. Completely
        unused slots count as 100% blank; partially filled slots contribute their
        actual measured content height.
        """
        score_by_slot = {s.slot_id: s for s in assignments}
        total_area = 0.0
        used_area = 0.0

        for slot in template.stories:
            slot_height = self.matcher.geometry.slot_height_mm(template.page, slot)
            slot_width = self.matcher.geometry.span_width_mm(
                template.page.column_count,
                slot.column_span,
            )
            area = max(0.0, slot_width * slot_height)
            total_area += area

            score = score_by_slot.get(slot.id)
            if score is None:
                continue

            if score.occupied_area_mm2 > 0:
                used_area += min(area, max(0.0, score.occupied_area_mm2))
            else:
                fill_ratio = min(
                    1.0,
                    max(0.0, score.required_height_mm / max(score.slot_height_mm, 1e-9)),
                )
                used_area += area * fill_ratio

        page_area = (
            self.matcher.geometry.content_width_mm
            * self.matcher.geometry.content_height_mm
        )
        if page_area <= 1e-9:
            return 0.0, 1.0

        # Absolute physical utilization: intentional gaps between template slots
        # are visible whitespace too. They are tolerated through page-type targets.
        utilization = min(1.0, max(0.0, used_area / page_area))
        blank_ratio = 1.0 - utilization

        if template.page.type == "front":
            target = self.config.front_page_utilization_target
        elif template.page.type == "special":
            target = self.config.special_page_utilization_target
        else:
            target = self.config.target_page_utilization

        allowed_blank = max(0.0, 1.0 - target)
        excess_blank = max(0.0, blank_ratio - allowed_blank)
        severe_blank = max(
            0.0,
            blank_ratio - self.config.severe_whitespace_threshold,
        )

        cost = (
            self.config.page_whitespace_penalty * (excess_blank ** 1.35)
            + self.config.severe_whitespace_penalty * (severe_blank ** 2)
        )
        return cost, utilization

    def _order_cost(
        self,
        article: Article,
        page_index: int,
        estimated_pages: int,
    ) -> float:
        if estimated_pages <= 1:
            position = 1.0
        else:
            position = page_index / max(1, estimated_pages - 1)

        cost = 0.0
        longness = len(article.markdown)
        if article.kind == "long" or longness > 9000:
            cost += max(0.0, 0.60 - position) * self.config.early_long_article_penalty

        if article.kind in {"report", "system_report", "health_report"}:
            cost += max(0.0, 0.72 - position) * self.config.early_report_penalty

        if article.preferred_page_type == "front" and page_index > 0:
            cost += 6.0

        return cost

    @staticmethod
    def _estimate_page_count(
        articles: list[Article],
        templates: list[Template],
    ) -> int:
        if not templates:
            return 1
        avg_slots = sum(len(t.stories) for t in templates) / len(templates)
        return max(1, math.ceil(len(articles) / max(avg_slots, 1.0)))
