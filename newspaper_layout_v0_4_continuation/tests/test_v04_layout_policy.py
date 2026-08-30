from newspaper_layout.dom_splitter import DOMSplitter
from newspaper_layout.html_components import markdown_to_html
from newspaper_layout.models import Article
from newspaper_layout.optimizer import LayoutOptimizer, OptimizerConfig
from newspaper_layout.templates import TemplateParser


def template(tid, page_type="interior", top=0.08, bottom=0.92):
    return TemplateParser().parse_dict({
        "template_id": tid,
        "personal_rating": 5,
        "page": {"type": page_type, "column_count": 5},
        "stories": [{
            "id": "A", "column_start": 0, "column_span": 5,
            "top": top, "bottom": bottom, "role": "normal",
            "headline_weight": "medium"
        }]
    })


def test_front_template_is_first_and_never_later():
    front = template("front", "front")
    interior = template("interior", "interior")
    articles = [
        Article(id="a", title="A", markdown="Text " * 150, priority=0.9),
        Article(id="b", title="B", markdown="Text " * 150, priority=0.5),
    ]
    plan = LayoutOptimizer(
        config=OptimizerConfig(beam_width=4, template_branching=4)
    ).optimize(articles, [front, interior])

    assert plan.pages[0].template_id == "front"
    assert all(p.template_id != "front" for p in plan.pages[1:])


def test_template_repetition_is_penalized():
    a = template("layout_A", top=0.07, bottom=0.90)
    b = template("layout_B", top=0.10, bottom=0.93)
    articles = [
        Article(id=str(i), title=f"Story {i}", markdown="Text " * 120, priority=0.5)
        for i in range(4)
    ]
    plan = LayoutOptimizer(
        config=OptimizerConfig(
            beam_width=8,
            template_branching=8,
            template_reuse_penalty=40,
            consecutive_same_template_penalty=180,
            recent_template_penalty=60,
        )
    ).optimize(articles, [a, b])

    ids = [p.template_id for p in plan.pages]
    assert len(set(ids)) == 2
    assert all(ids[i] != ids[i-1] for i in range(1, len(ids)))


def test_system_report_is_pushed_after_normal_story():
    t = template("single")
    normal = Article(id="normal", title="Normal", markdown="Text " * 100, priority=0.5)
    report = Article(id="report", title="Health", markdown="Text " * 100, priority=0.5, kind="system_report")
    plan = LayoutOptimizer(
        config=OptimizerConfig(
            beam_width=4, template_branching=4, early_report_penalty=150
        )
    ).optimize([report, normal], [t])
    assert plan.pages[0].assignments[0].article_id == "normal"


def test_markdown_table_and_duplicate_heading_fix():
    body = "# Same title!\n\n| a | b |\n|---|---|\n|1|2|"
    rendered = markdown_to_html(body, title="Same title")
    assert rendered.count("<h1>") == 0
    assert "<table>" in rendered


def test_resplit_tail_does_not_inherit_head_pin():
    head = Article(
        id="am15",
        title="Long",
        markdown="Body " * 80,
        kind="long",
        metadata={
            "original_article_id": "am15",
            "fragment_index": 1,
            "fixed_page_index": 7,
            "continuation_to_page": "?",
        },
    )
    tail = DOMSplitter.__new__(DOMSplitter)._fragment_article(
        head,
        markdown="Remainder " * 40,
        has_tail=False,
        source_page_number=8,
        tail=True,
    )
    assert tail.id == "am15::cont2"
    assert "fixed_page_index" not in tail.metadata
    assert tail.metadata.get("minimum_page_index") is None
    assert tail.metadata["continuation"] is True
