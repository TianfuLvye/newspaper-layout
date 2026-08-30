from newspaper_layout.chromium_measure import ChromiumArticleMeasurer
from newspaper_layout.models import Article, ArticleImage


def test_chromium_exact_measurement_runs():
    article = Article(
        id="exact",
        title="A browser measured newspaper headline",
        markdown=("## Section\n\n" + ("Browser typography measurement text. " * 80)),
        images=[ArticleImage(1600, 900)],
    )
    with ChromiumArticleMeasurer() as m:
        one = m.measure_at_width(
            article, 52.0,
            headline_weight="large",
            image_style="large",
            image_position="top",
            body_columns=1,
        )
        two = m.measure_at_width(
            article, 108.0,
            headline_weight="large",
            image_style="large",
            image_position="top",
            body_columns=2,
        )
    assert one["required_height_mm"] > 0
    assert two["required_height_mm"] > 0
    assert two["required_height_mm"] < one["required_height_mm"]
    assert 3.0 < one["px_per_mm"] < 4.5


def test_side_image_reports_visual_occupancy_not_bounding_box():
    article = Article(
        id="side",
        title="Side image test",
        markdown="Short body text. " * 20,
        images=[ArticleImage(1200, 1600)],
    )
    width_mm = 110.0
    with ChromiumArticleMeasurer() as m:
        result = m.measure_at_width(
            article,
            width_mm,
            headline_weight="medium",
            image_style="large",
            image_position="left",
            body_columns=2,
        )

    bounding_area = width_mm * result["required_height_mm"]
    assert result["occupied_area_mm2"] > 0
    assert result["occupied_area_mm2"] < bounding_area
