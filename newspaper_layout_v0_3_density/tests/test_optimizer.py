from newspaper_layout.models import Article
from newspaper_layout.optimizer import LayoutOptimizer, OptimizerConfig
from newspaper_layout.templates import TemplateParser


def test_optimizer_assigns_articles():
    template = TemplateParser().parse_dict({
        "template_id": "t",
        "personal_rating": 5,
        "page": {"type": "interior", "column_count": 5},
        "stories": [
            {
                "id": "A", "column_start": 0, "column_span": 3,
                "top": 0.05, "bottom": 0.95, "role": "lead",
                "headline_weight": "large"
            },
            {
                "id": "B", "column_start": 3, "column_span": 2,
                "top": 0.05, "bottom": 0.95, "role": "normal",
                "headline_weight": "medium"
            },
        ],
    })
    articles = [
        Article(id="1", title="Main", markdown="Text " * 300, priority=0.9),
        Article(id="2", title="Other", markdown="Text " * 150, priority=0.5),
    ]
    plan = LayoutOptimizer(
        config=OptimizerConfig(beam_width=2, template_branching=2)
    ).optimize(articles, [template])
    assert not plan.unassigned_article_ids
    assert len(plan.pages) == 1
    assert len(plan.pages[0].assignments) == 2
