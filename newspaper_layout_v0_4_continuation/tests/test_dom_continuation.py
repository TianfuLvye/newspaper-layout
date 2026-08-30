from newspaper_layout.chromium_measure import ChromiumArticleMeasurer
from newspaper_layout.continuation_allocator import ContinuationAllocator
from newspaper_layout.dom_splitter import DOMSplitter
from newspaper_layout.matching import SlotMatcher
from newspaper_layout.models import Article
from newspaper_layout.optimizer import LayoutOptimizer, OptimizerConfig
from newspaper_layout.renderer import HTMLNewspaperRenderer
from newspaper_layout.templates import TemplateParser


def make_template():
    return TemplateParser().parse_dict({
        "template_id": "continuation_page",
        "personal_rating": 5,
        "page": {"type": "interior", "column_count": 5},
        "stories": [{
            "id": "A", "column_start": 0, "column_span": 5,
            "top": 0.08, "bottom": 0.82,
            "role": "normal", "headline_weight": "medium"
        }]
    })


def long_article():
    paras = []
    for i in range(28):
        if i in {0, 8, 16, 24}:
            paras.append(f"## Section {i//8 + 1}")
        paras.append(
            f"Paragraph {i}. " + "This is substantial newspaper body copy. " * 24
        )
    return Article(
        id="long",
        title="A long article that genuinely needs continuation",
        markdown="\n\n".join(paras),
        priority=0.7,
        kind="long",
    )


def test_dom_splitter_finds_a_real_breakpoint():
    t = make_template()
    article = long_article()
    with ChromiumArticleMeasurer() as measurer:
        splitter = DOMSplitter(measurer)
        result = splitter.split_for_slot(
            article, t, t.stories[0], source_page_number=1
        )
        assert result.tail is not None
        assert len(result.head.markdown) < len(article.markdown)
        assert len(result.tail.markdown) < len(article.markdown)
        assert result.head.metadata["continuation_to_page"] == "?"
        assert result.tail.metadata["continuation"] is True

        head_measure = measurer.measure_for_slot(result.head, t, t.stories[0])
        assert head_measure["required_height_mm"] <= result.slot_height_mm + 0.4


def test_allocator_reflows_until_no_predicted_overflow_and_links_pages():
    t = make_template()
    article = long_article()

    with ChromiumArticleMeasurer() as measurer:
        matcher = SlotMatcher(measurer=measurer)
        optimizer = LayoutOptimizer(
            matcher=matcher,
            config=OptimizerConfig(
                beam_width=3,
                template_branching=3,
                max_pages=12,
            ),
        )
        initial = optimizer.optimize([article], [t])
        assert any(
            s.predicted_splits
            for p in initial.pages for s in p.assignments
        )

        allocation = ContinuationAllocator(
            optimizer, DOMSplitter(measurer)
        ).allocate(initial, [article], [t])

        assert allocation.split_count >= 1
        assert all(
            s.predicted_splits == 0
            for p in allocation.plan.pages for s in p.assignments
        )
        assert len(allocation.plan.pages) >= 2

        doc = HTMLNewspaperRenderer().render(
            allocation.plan, allocation.articles, [t]
        )
        assert "下转第" in doc
        assert "上接第" in doc
