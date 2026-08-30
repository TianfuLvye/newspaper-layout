from newspaper_layout.models import (
    Article, LayoutPlan, PageAssignment, SlotScore
)
from newspaper_layout.renderer import HTMLNewspaperRenderer, RenderConfig
from newspaper_layout.templates import TemplateParser


def test_renderer_outputs_a3_html():
    template = TemplateParser().parse_dict({
        "template_id": "r",
        "personal_rating": 5,
        "page": {"type": "interior", "column_count": 5},
        "stories": [{
            "id": "A", "column_start": 0, "column_span": 5,
            "top": 0.08, "bottom": 0.95, "role": "lead",
            "headline_weight": "large"
        }],
    })
    article = Article(
        id="1",
        title="Rendered headline",
        markdown="## Subhead\n\nBody text " * 20,
    )
    score = SlotScore(
        article_id="1", slot_id="A", total=0, fit=0, role=0,
        image=0, headline=0, kind=0, split=0, predicted_splits=0,
        required_height_mm=100, slot_height_mm=300,
    )
    plan = LayoutPlan(
        pages=[PageAssignment("r", 0, [score], 0, 0, 0)],
        total_cost=0,
    )
    doc = HTMLNewspaperRenderer(
        RenderConfig(title="Test Paper", debug=True)
    ).render(plan, [article], [template])
    assert "297mm" in doc
    assert "420mm" in doc
    assert "Rendered headline" in doc
    assert "debug-layout" in doc
