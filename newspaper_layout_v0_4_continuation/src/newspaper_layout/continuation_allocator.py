from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .dom_splitter import DOMSplitter, DOMSplitError
from .models import Article, LayoutPlan, PageAssignment, Template
from .optimizer import LayoutOptimizer


@dataclass(frozen=True)
class ContinuationAllocatorConfig:
    max_reflow_rounds: int = 64


@dataclass
class ContinuationAllocationResult:
    plan: LayoutPlan
    articles: list[Article]
    split_count: int
    fragment_count: int
    reflow_rounds: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "split_count": self.split_count,
            "fragment_count": self.fragment_count,
            "reflow_rounds": self.reflow_rounds,
            "plan": self.plan.to_dict(),
            "articles": [a.to_dict() for a in self.articles],
        }


class ContinuationAllocator:
    """
    Real continuation allocator with suffix reflow.

    Important density rule:
    when page N contains an overflow, page N is *not* frozen. Only pages < N are
    frozen. The overflowing article is split for its current slot, then page N and
    all later material are optimized again together.

    Constraints:
    - the head fragment is pinned to page N;
    - the tail cannot appear before page N+1;
    - other stories from page N are free to move;
    - later stories and continuation tails can share templates.

    This avoids the common bad outcome where a small tail gets a mostly empty
    dedicated continuation page.
    """

    def __init__(
        self,
        optimizer: LayoutOptimizer,
        splitter: DOMSplitter,
        *,
        config: ContinuationAllocatorConfig | None = None,
    ):
        self.optimizer = optimizer
        self.splitter = splitter
        self.config = config or ContinuationAllocatorConfig()

    @property
    def matcher(self):
        return self.optimizer.matcher

    def allocate(
        self,
        plan: LayoutPlan,
        articles: list[Article],
        templates: list[Template],
    ) -> ContinuationAllocationResult:
        article_map = {a.id: a for a in articles}
        template_map = {t.template_id: t for t in templates}

        fixed_pages: list[PageAssignment] = []
        current = plan
        split_count = 0
        rounds = 0

        while rounds < self.config.max_reflow_rounds:
            rounds += 1
            overflow_local = self._first_overflow_page(current)
            if overflow_local is None:
                fixed_pages.extend(current.pages)
                current = LayoutPlan([], 0.0, current.unassigned_article_ids)
                break

            # Freeze only the clean prefix. The overflow source page remains part of
            # the reflow pool so its ordinary stories can move and fill continuation pages.
            for page in current.pages[:overflow_local]:
                page.page_index = len(fixed_pages)
                fixed_pages.append(page)

            source = current.pages[overflow_local]
            source_abs_index = len(fixed_pages)
            template = template_map[source.template_id]
            slots = {s.id: s for s in template.stories}

            reflow_articles: list[Article] = []
            seen_ids: set[str] = set()

            # Split every overflowing story on the source page using the exact current slot.
            for score in source.assignments:
                article = article_map[score.article_id]
                if score.predicted_splits <= 0:
                    self._append_unique(reflow_articles, seen_ids, article)
                    continue

                slot = slots[score.slot_id]
                result = self.splitter.split_for_slot(
                    article,
                    template,
                    slot,
                    source_page_number=source_abs_index + 1,
                )
                if result.tail is None:
                    self._append_unique(reflow_articles, seen_ids, result.head)
                    article_map[result.head.id] = result.head
                    continue

                # The first fragment must stay on this source page. The remainder may
                # start on the next page, never on the same page.
                result.head.metadata["fixed_page_index"] = source_abs_index
                result.tail.metadata.pop("fixed_page_index", None)
                result.tail.metadata["minimum_page_index"] = source_abs_index + 1
                result.tail.metadata["continuation_source_page_index"] = source_abs_index

                article_map[result.head.id] = result.head
                article_map[result.tail.id] = result.tail
                self._append_unique(reflow_articles, seen_ids, result.head)
                self._append_unique(reflow_articles, seen_ids, result.tail)
                split_count += 1

            # The rest of the source page and all later pages are movable.
            for page in current.pages[overflow_local + 1:]:
                for score in page.assignments:
                    article = article_map.get(score.article_id)
                    if article is not None:
                        self._append_unique(reflow_articles, seen_ids, article)
            for aid in current.unassigned_article_ids:
                article = article_map.get(aid)
                if article is not None:
                    self._append_unique(reflow_articles, seen_ids, article)

            if not reflow_articles:
                current = LayoutPlan([], 0.0, [])
                break

            current = self.optimizer.optimize(
                reflow_articles,
                templates,
                start_page_index=source_abs_index,
                prior_pages=fixed_pages,
            )

            # A pinned head may become impossible only if no template on the source
            # page has enough usable slots. Surface that loudly instead of clipping.
            missing_pinned = [
                a.id for a in reflow_articles
                if a.metadata.get("fixed_page_index") == source_abs_index
                and all(
                    a.id != s.article_id
                    for p in current.pages[:1]
                    for s in p.assignments
                )
            ]
            if missing_pinned:
                raise DOMSplitError(
                    "Could not place pinned continuation head(s) on source page: "
                    + ", ".join(missing_pinned)
                )

        else:
            raise RuntimeError(
                f"ContinuationAllocator exceeded {self.config.max_reflow_rounds} reflow rounds"
            )

        final_pages = fixed_pages + current.pages
        for i, page in enumerate(final_pages):
            page.page_index = i

        final_plan = LayoutPlan(
            pages=final_pages,
            total_cost=sum(p.total_cost for p in final_pages)
            + len(current.unassigned_article_ids) * 1000.0,
            unassigned_article_ids=list(current.unassigned_article_ids),
            metadata=dict(plan.metadata),
        )

        self._link_fragments(final_plan, article_map)
        fragments = [
            a for a in article_map.values()
            if a.metadata.get("original_article_id")
        ]
        final_plan.metadata.update({
            "continuation_allocator": "dom-reflow-v2",
            "continuation_splits": split_count,
            "continuation_fragments": len(fragments),
            "continuation_reflow_rounds": rounds,
        })

        return ContinuationAllocationResult(
            plan=final_plan,
            articles=list(article_map.values()),
            split_count=split_count,
            fragment_count=len(fragments),
            reflow_rounds=rounds,
        )

    @staticmethod
    def _append_unique(target, seen, article):
        if article.id not in seen:
            target.append(article)
            seen.add(article.id)

    @staticmethod
    def _first_overflow_page(plan: LayoutPlan) -> int | None:
        for i, page in enumerate(plan.pages):
            if any(s.predicted_splits > 0 for s in page.assignments):
                return i
        return None

    def _link_fragments(
        self,
        plan: LayoutPlan,
        article_map: dict[str, Article],
    ) -> None:
        page_for_article: dict[str, int] = {}
        for page in plan.pages:
            for score in page.assignments:
                page_for_article[score.article_id] = page.page_index + 1

        groups: dict[str, list[Article]] = {}
        for article in article_map.values():
            original = article.metadata.get("original_article_id")
            if original:
                groups.setdefault(str(original), []).append(article)

        for _, fragments in groups.items():
            fragments.sort(key=lambda a: int(a.metadata.get("fragment_index", 1)))
            located = [a for a in fragments if a.id in page_for_article]

            for article in located:
                article.metadata.pop("continuation_from_page", None)
                article.metadata.pop("continuation_to_page", None)
                article.metadata.pop("fixed_page_index", None)
                article.metadata.pop("minimum_page_index", None)

            for i, article in enumerate(located):
                if i > 0:
                    article.metadata["continuation"] = True
                    article.metadata["continuation_from_page"] = page_for_article[
                        located[i - 1].id
                    ]
                    article.metadata["continuation_source_page_index"] = (
                        page_for_article[located[i - 1].id] - 1
                    )
                if i + 1 < len(located):
                    article.metadata["continuation_to_page"] = page_for_article[
                        located[i + 1].id
                    ]
