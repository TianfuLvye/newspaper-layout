from newspaper_layout.matching import SlotMatcher
from newspaper_layout.models import Article
from newspaper_layout.optimizer import LayoutOptimizer, OptimizerConfig
from newspaper_layout.templates import TemplateParser


class FixedHeightMeasurer:
    def measure_for_slot(self, article, template, slot):
        required = float(article.metadata["height_mm"])
        width = 273.0 * (slot.column_span / template.page.column_count)
        return {
            "required_height_mm": required,
            "title_height_mm": 10.0,
            "body_height_mm": max(0.0, required - 10.0),
            "image_height_mm": 0.0,
            "occupied_area_mm2": width * required,
            "intrinsic_cost": 0.0,
            "title_lines": 1.0,
        }


def make_template(template_id, bottom, rating=5):
    return TemplateParser().parse_dict({
        "template_id": template_id,
        "personal_rating": rating,
        "page": {"type": "interior", "column_count": 5},
        "stories": [
            {
                "id": "A", "column_start": 0, "column_span": 5,
                "top": 0.05, "bottom": bottom,
                "role": "normal", "headline_weight": "medium"
            }
        ],
    })


def test_half_empty_slot_is_strongly_penalized():
    matcher = SlotMatcher(measurer=FixedHeightMeasurer())
    article = Article(
        id="a", title="A", markdown="x",
        metadata={"height_mm": 95.0},
    )
    compact = make_template("compact", 0.31)
    huge = make_template("huge", 0.88)

    compact_score = matcher.score(article, compact, compact.stories[0])
    huge_score = matcher.score(article, huge, huge.stories[0])

    assert huge_score.fit > compact_score.fit + 20.0


def test_avoidable_continuation_gets_extra_penalty():
    matcher = SlotMatcher(measurer=FixedHeightMeasurer())
    optimizer = LayoutOptimizer(
        matcher=matcher,
        config=OptimizerConfig(
            beam_width=2,
            template_branching=2,
            article_shortlist=4,
        ),
    )
    template = TemplateParser().parse_dict({
        "template_id": "mixed",
        "personal_rating": 5,
        "page": {"type": "interior", "column_count": 5},
        "stories": [
            {
                "id": "small", "column_start": 0, "column_span": 2,
                "top": 0.05, "bottom": 0.42,
                "role": "normal", "headline_weight": "medium"
            },
            {
                "id": "large", "column_start": 2, "column_span": 3,
                "top": 0.05, "bottom": 0.78,
                "role": "normal", "headline_weight": "medium"
            },
        ],
    })
    long = Article(
        id="long", title="Long", markdown="x",
        metadata={"height_mm": 220.0},
    )
    short = Article(
        id="short", title="Short", markdown="x",
        metadata={"height_mm": 90.0},
    )

    page = optimizer._best_page_assignment(
        [long, short],
        template,
        page_index=0,
        estimated_pages=1,
    )

    assert page is not None
    # The long article has an unsplit home in the large slot. If it were put in
    # the small slot, that continuation would be avoidable on this very page.
    long_assignment = next(a for a in page.assignments if a.article_id == "long")
    assert long_assignment.slot_id == "large"
    assert long_assignment.predicted_splits == 0

def test_optimizer_prefers_unsplit_home():
    matcher = SlotMatcher(measurer=FixedHeightMeasurer())
    optimizer = LayoutOptimizer(
        matcher=matcher,
        config=OptimizerConfig(
            beam_width=4,
            template_branching=4,
            article_shortlist=4,
        ),
    )
    article = Article(
        id="long", title="Long", markdown="x",
        metadata={"height_mm": 220.0},
    )
    too_small = make_template("small", 0.45, rating=5)
    fits = make_template("fits", 0.75, rating=4)

    plan = optimizer.optimize([article], [too_small, fits])
    assert plan.pages
    assert plan.pages[0].template_id == "fits"
    assert plan.pages[0].assignments[0].predicted_splits == 0
