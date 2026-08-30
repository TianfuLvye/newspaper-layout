from newspaper_layout.templates import TemplateParser, TemplateValidationError


def test_minimal_template_parses():
    data = {
        "template_version": 1,
        "template_id": "x",
        "personal_rating": 4,
        "page": {
            "type": "interior",
            "column_count": 5,
            "content_left": 0.02,
            "content_right": 0.98,
            "content_top": 0,
            "content_bottom": 1,
        },
        "stories": [
            {
                "id": "A",
                "column_start": 0,
                "column_span": 4,
                "top": 0.08,
                "bottom": 0.80,
                "role": "lead",
                "image_style": "large",
                "image_position": "top",
                "headline_weight": "large",
            },
            {
                "id": "B",
                "column_start": 4,
                "column_span": 1,
                "top": 0.08,
                "bottom": 0.80,
                "role": "normal",
                "headline_weight": "medium",
            },
        ],
    }
    template = TemplateParser().parse_dict(data)
    assert template.template_id == "x"
    assert template.story_count == 2


def test_overlap_rejected():
    data = {
        "template_id": "bad",
        "page": {"type": "interior", "column_count": 5},
        "stories": [
            {
                "id": "A", "column_start": 0, "column_span": 3,
                "top": 0.1, "bottom": 0.8
            },
            {
                "id": "B", "column_start": 2, "column_span": 3,
                "top": 0.2, "bottom": 0.7
            },
        ],
    }
    try:
        TemplateParser().parse_dict(data)
    except TemplateValidationError:
        return
    raise AssertionError("expected overlap validation error")
