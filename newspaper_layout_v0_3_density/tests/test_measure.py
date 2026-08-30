from newspaper_layout.measure import ArticleMeasurer
from newspaper_layout.models import Article, ArticleImage


def test_width_curve_gets_shorter():
    a = Article(
        id="a",
        title="A fairly long title for testing",
        markdown=("This is a paragraph with enough words to wrap across several lines. " * 30),
        images=[ArticleImage(1600, 900)],
    )
    p = ArticleMeasurer().profile(
        a,
        5,
        headline_weight="medium",
        image_style="large",
        image_position="top",
    )
    heights = [x.required_height_mm for x in p.candidates]
    assert heights[-1] < heights[0]
