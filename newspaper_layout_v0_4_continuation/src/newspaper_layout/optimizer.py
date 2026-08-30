from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from itertools import combinations
import math

from .matching import SlotMatcher
from .models import Article, LayoutPlan, PageAssignment, SlotScore, Template


@dataclass(frozen=True)
class OptimizerConfig:
    beam_width: int = 8
    template_branching: int = 10
    article_shortlist: int = 14
    max_pages: int = 32

    early_long_article_penalty: float = 12.0
    early_report_penalty: float = 70.0
    system_report_tail_fraction: float = 0.82
    report_tail_fraction: float = 0.70
    continuation_delay_penalty: float = 85.0

    empty_slot_penalty: float = 140.0
    target_page_utilization: float = 0.90
    front_page_utilization_target: float = 0.70
    special_page_utilization_target: float = 0.80
    page_whitespace_penalty: float = 700.0
    severe_whitespace_penalty: float = 1400.0
    severe_whitespace_threshold: float = 0.30
    page_open_penalty: float = 35.0

    # Visual variety. Exact repeats are much more expensive than family similarity.
    template_reuse_penalty: float = 28.0
    consecutive_same_template_penalty: float = 135.0
    recent_template_penalty: float = 42.0
    template_family_penalty: float = 16.0
    recent_template_window: int = 4


@dataclass
class _BeamState:
    remaining_ids: tuple[str, ...]
    pages: list[PageAssignment]
    total_cost: float


class LayoutOptimizer:
    """
    V0.4 planner.

    New invariants:
    - a front template may only be used on page 1;
    - when front templates exist, page 1 uses one;
    - repeated and consecutively repeated layouts are penalized;
    - continuation fragments prefer the next page after their source;
    - report/system pages are strongly pushed toward the tail.
    """

    def __init__(
        self,
        matcher: SlotMatcher | None = None,
        config: OptimizerConfig | None = None,
    ):
        self.matcher = matcher or SlotMatcher()
        self.config = config or OptimizerConfig()
        self._template_lookup: dict[str, Template] = {}

    def optimize(
        self,
        articles: list[Article],
        templates: list[Template],
        *,
        page_type: str | None = None,
        start_page_index: int = 0,
        prior_pages: list[PageAssignment] | None = None,
    ) -> LayoutPlan:
        if not articles:
            return LayoutPlan([], 0.0, [])
        if not templates:
            return LayoutPlan([], math.inf, [a.id for a in articles])

        article_by_id = {a.id: a for a in articles}
        if len(article_by_id) != len(articles):
            raise ValueError("Article ids must be unique")

        prior_pages = list(prior_pages or [])
        usable_templates = [
            t for t in templates
            if page_type is None or t.page.type == page_type
        ]
        if not usable_templates:
            usable_templates = templates[:]

        usable_templates = sorted(
            usable_templates,
            key=lambda t: (-t.personal_rating, -len(t.stories), t.template_id)
        )
        self._template_lookup = {t.template_id: t for t in templates}

        initial = _BeamState(
            remaining_ids=tuple(a.id for a in articles),
            pages=[],
            total_cost=0.0,
        )
        beam = [initial]
        completed: list[_BeamState] = []

        suffix_pages = self._estimate_page_count(articles, usable_templates)
        estimated_total_pages = max(
            start_page_index + suffix_pages,
            len(prior_pages) + suffix_pages,
        )

        for local_page_index in range(self.config.max_pages):
            page_index = start_page_index + local_page_index
            next_states: list[_BeamState] = []

            for state in beam:
                if not state.remaining_ids:
                    completed.append(state)
                    continue

                remaining = [article_by_id[x] for x in state.remaining_ids]
                history = prior_pages + state.pages

                eligible = self._eligible_templates(
                    usable_templates,
                    page_index=page_index,
                    explicit_page_type=page_type,
                )
                template_candidates = self._template_candidates(
                    eligible,
                    len(remaining),
                    history,
                )

                for template in template_candidates:
                    assignment = self._best_page_assignment(
                        remaining,
                        template,
                        page_index=page_index,
                        estimated_pages=estimated_total_pages,
                    )
                    if assignment is None:
                        continue

                    variety_cost = self._template_variety_cost(history, template)
                    assignment.variety_cost = variety_cost
                    assignment.total_cost += variety_cost

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

            if not next_states:
                break

            next_states.sort(
                key=lambda s: (
                    s.total_cost + len(s.remaining_ids) * 65.0,
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

    def _eligible_templates(
        self,
        templates: list[Template],
        *,
        page_index: int,
        explicit_page_type: str | None,
    ) -> list[Template]:
        if explicit_page_type is not None:
            return templates

        fronts = [t for t in templates if t.page.type == "front"]
        if page_index == 0 and fronts:
            return fronts

        non_front = [t for t in templates if t.page.type != "front"]
        return non_front or templates

    def _template_candidates(
        self,
        templates: list[Template],
        remaining_count: int,
        history: list[PageAssignment],
    ) -> list[Template]:
        ranked = sorted(
            templates,
            key=lambda t: (
                abs(min(len(t.stories), remaining_count) - len(t.stories)),
                self._template_variety_cost(history, t),
                -t.personal_rating,
                t.template_id,
            ),
        )
        return ranked[: self.config.template_branching]

    def _template_family(self, template: Template) -> tuple:
        return (
            len(template.stories),
            tuple(s.column_span for s in template.stories),
            tuple(round(s.normalized_height, 1) for s in template.stories),
            tuple(s.role for s in template.stories),
        )

    def _template_variety_cost(
        self,
        history: list[PageAssignment],
        template: Template,
    ) -> float:
        if not history:
            return 0.0

        ids = [p.template_id for p in history]
        reuse_count = ids.count(template.template_id)
        cost = self.config.template_reuse_penalty * (reuse_count ** 1.45)

        if ids[-1] == template.template_id:
            cost += self.config.consecutive_same_template_penalty

        recent_ids = ids[-self.config.recent_template_window:]
        if template.template_id in recent_ids:
            distance = len(recent_ids) - 1 - recent_ids[::-1].index(template.template_id)
            # Presence anywhere in the recent window matters; consecutive was handled above.
            cost += self.config.recent_template_penalty * (1.0 + 0.15 * distance)

        family = self._template_family(template)
        recent_family_count = 0
        for p in history[-self.config.recent_template_window:]:
            old = self._template_lookup.get(p.template_id)
            if old is not None and self._template_family(old) == family:
                recent_family_count += 1
        cost += self.config.template_family_penalty * recent_family_count
        return cost


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

        active_count = min(slot_count, len(articles))

        # V0.3 always took template.stories[:active_count]. That is wrong when the
        # last page has fewer stories than the template: a short continuation could
        # be forced into a giant lead slot while a much better small slot existed.
        if active_count == slot_count:
            slot_sets = [tuple(template.stories)]
        else:
            slot_sets = list(combinations(template.stories, active_count))

        best: PageAssignment | None = None
        for use_slots in slot_sets:
            candidate = self._best_page_assignment_for_slots(
                articles,
                template,
                list(use_slots),
                page_index=page_index,
                estimated_pages=estimated_pages,
            )
            if candidate is not None and (
                best is None or candidate.total_cost < best.total_cost
            ):
                best = candidate
        return best

    def _best_page_assignment_for_slots(
        self,
        articles: list[Article],
        template: Template,
        use_slots,
        *,
        page_index: int,
        estimated_pages: int,
    ) -> PageAssignment | None:
        slot_count = len(template.stories)
        union_ids: set[str] = set()

        per_slot_limit = max(
            4,
            min(
                self.config.article_shortlist,
                max(4, self.config.article_shortlist // max(1, len(use_slots)) + 5),
            ),
        )

        for slot in use_slots:
            scored = [(a, self.matcher.score(a, template, slot)) for a in articles]
            scored.sort(key=lambda pair: pair[1].total)
            union_ids.update(a.id for a, _ in scored[:per_slot_limit])

        pinned_ids = {
            a.id for a in articles
            if a.metadata.get("fixed_page_index") is not None
            and int(a.metadata["fixed_page_index"]) == page_index
        }
        union_ids.update(pinned_ids)

        shortlist_articles = [a for a in articles if a.id in union_ids]
        if len(shortlist_articles) > self.config.article_shortlist:
            agg = []
            for a in shortlist_articles:
                best_score = min(
                    self.matcher.score(a, template, slot).total
                    for slot in use_slots
                )
                agg.append((best_score, a))
            agg.sort(key=lambda x: (0 if x[1].id in pinned_ids else 1, x[0]))
            shortlist_articles = [a for _, a in agg[: self.config.article_shortlist]]
            existing = {a.id for a in shortlist_articles}
            for a in articles:
                if a.id in pinned_ids and a.id not in existing:
                    shortlist_articles.append(a)
                    existing.add(a.id)

        if len(shortlist_articles) < len(use_slots):
            existing = {a.id for a in shortlist_articles}
            for a in articles:
                if a.id not in existing:
                    shortlist_articles.append(a)
                    existing.add(a.id)
                if len(shortlist_articles) >= len(use_slots):
                    break

        score_matrix: list[list[SlotScore]] = []
        for slot in use_slots:
            score_matrix.append([
                self.matcher.score(a, template, slot)
                for a in shortlist_articles
            ])

        required_mask = 0
        for ai, article in enumerate(shortlist_articles):
            fixed = article.metadata.get("fixed_page_index")
            if fixed is not None and int(fixed) == page_index:
                required_mask |= (1 << ai)

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
                if required_mask and (used_mask & required_mask) != required_mask:
                    return math.inf, ()
                return 0.0, ()
            best_cost = math.inf
            best_choice = ()
            for ai, article in enumerate(shortlist_articles):
                if used_mask & (1 << ai):
                    continue

                fixed = article.metadata.get("fixed_page_index")
                minimum = article.metadata.get("minimum_page_index")
                if fixed is not None and int(fixed) != page_index:
                    continue
                if minimum is not None and page_index < int(minimum):
                    continue

                score = score_matrix[slot_idx][ai]
                tail_cost, tail_choice = dp(slot_idx + 1, used_mask | (1 << ai))
                cost = (
                    score.total
                    + avoidable_split_extra(ai, score)
                    + self._order_cost(
                        shortlist_articles[ai],
                        page_index,
                        estimated_pages,
                    )
                    + tail_cost
                )
                if cost < best_cost:
                    best_cost = cost
                    best_choice = (ai,) + tail_choice
            return best_cost, best_choice

        dp_cost, choices = dp(0, 0)
        if math.isinf(dp_cost) or not choices:
            return None

        assignments = [
            score_matrix[slot_idx][ai]
            for slot_idx, ai in enumerate(choices)
        ]
        assigned_articles = [shortlist_articles[ai] for ai in choices]

        template_cost = self.matcher.template_prior_cost(template)
        unused_slots = max(0, slot_count - len(assignments))
        template_cost += unused_slots * self.config.empty_slot_penalty

        order_cost = sum(
            self._order_cost(a, page_index, estimated_pages)
            for a in assigned_articles
        )

        whitespace_cost, utilization = self._page_whitespace_cost(
            template, assignments
        )

        continuation_cost = sum(
            avoidable_split_extra(ai, score_matrix[slot_idx][ai])
            for slot_idx, ai in enumerate(choices)
        )

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
            variety_cost=0.0,
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
        score_by_slot = {s.slot_id: s for s in assignments}
        used_area = 0.0

        for slot in template.stories:
            slot_height = self.matcher.geometry.slot_height_mm(template.page, slot)
            slot_width = self.matcher.geometry.span_width_mm(
                template.page.column_count, slot.column_span
            )
            area = max(0.0, slot_width * slot_height)
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
            cost += max(0.0, 0.55 - position) * self.config.early_long_article_penalty

        if article.kind in {"system_report", "health_report"}:
            cost += (
                max(0.0, self.config.system_report_tail_fraction - position)
                * self.config.early_report_penalty
            )
        elif article.kind == "report":
            cost += (
                max(0.0, self.config.report_tail_fraction - position)
                * self.config.early_report_penalty
                * 0.72
            )

        if article.preferred_page_type == "front" and page_index > 0:
            cost += 18.0

        if article.metadata.get("continuation"):
            source_index = article.metadata.get("continuation_source_page_index")
            if source_index is not None:
                desired = int(source_index) + 1
                if page_index < desired:
                    cost += 10000.0
                elif page_index > desired:
                    cost += (
                        page_index - desired
                    ) * self.config.continuation_delay_penalty

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
