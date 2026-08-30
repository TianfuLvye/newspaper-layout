from __future__ import annotations

from dataclasses import dataclass, asdict
from collections import Counter
import math
import statistics
from typing import Any

from .models import Template


@dataclass
class TemplateFeatures:
    template_id: str
    story_count: int
    column_count: int
    page_type: str
    personal_rating: int
    width_spans: list[int]
    normalized_heights: list[float]
    normalized_areas: list[float]
    role_counts: dict[str, int]
    image_style_counts: dict[str, int]
    image_position_counts: dict[str, int]
    headline_counts: dict[str, int]
    largest_story_area: float
    area_fragmentation: float
    width_variance: float
    vertical_balance: float
    horizontal_balance: float
    top_alignment_pairs: int
    bottom_alignment_pairs: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class TemplateFeatureExtractor:
    def extract(self, template: Template) -> TemplateFeatures:
        cc = template.page.column_count
        widths = [s.column_span for s in template.stories]
        heights = [s.bottom - s.top for s in template.stories]
        areas = [(s.column_span / cc) * (s.bottom - s.top) for s in template.stories]

        total_area = sum(areas) or 1.0
        largest = max(areas) if areas else 0.0
        fragmentation = 1.0 - largest / total_area

        weighted_y = 0.0
        weighted_x = 0.0
        for s, a in zip(template.stories, areas):
            cy = (s.top + s.bottom) / 2
            cx = (s.column_start + s.column_span / 2) / cc
            weighted_y += cy * a
            weighted_x += cx * a
        vertical_balance = weighted_y / total_area
        horizontal_balance = weighted_x / total_area

        top_align = 0
        bottom_align = 0
        for i, a in enumerate(template.stories):
            for b in template.stories[i + 1:]:
                if abs(a.top - b.top) <= 0.012:
                    top_align += 1
                if abs(a.bottom - b.bottom) <= 0.012:
                    bottom_align += 1

        return TemplateFeatures(
            template_id=template.template_id,
            story_count=len(template.stories),
            column_count=cc,
            page_type=template.page.type,
            personal_rating=template.personal_rating,
            width_spans=widths,
            normalized_heights=heights,
            normalized_areas=areas,
            role_counts=dict(Counter(s.role for s in template.stories)),
            image_style_counts=dict(Counter(
                s.image_style for s in template.stories if s.image_style is not None
            )),
            image_position_counts=dict(Counter(
                s.image_position for s in template.stories if s.image_position is not None
            )),
            headline_counts=dict(Counter(s.headline_weight for s in template.stories)),
            largest_story_area=largest,
            area_fragmentation=fragmentation,
            width_variance=statistics.pvariance(widths) if len(widths) > 1 else 0.0,
            vertical_balance=vertical_balance,
            horizontal_balance=horizontal_balance,
            top_alignment_pairs=top_align,
            bottom_alignment_pairs=bottom_align,
        )
