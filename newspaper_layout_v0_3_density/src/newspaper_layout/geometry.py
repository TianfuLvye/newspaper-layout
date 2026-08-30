from __future__ import annotations

from dataclasses import dataclass

from .models import TemplatePage, StorySlot


@dataclass(frozen=True)
class PageGeometry:
    width_mm: float = 297.0
    height_mm: float = 420.0
    margin_left_mm: float = 12.0
    margin_right_mm: float = 12.0
    margin_top_mm: float = 12.0
    margin_bottom_mm: float = 12.0
    gutter_mm: float = 4.0

    @property
    def content_width_mm(self) -> float:
        return self.width_mm - self.margin_left_mm - self.margin_right_mm

    @property
    def content_height_mm(self) -> float:
        return self.height_mm - self.margin_top_mm - self.margin_bottom_mm

    def column_width_mm(self, column_count: int) -> float:
        gutters = max(0, column_count - 1) * self.gutter_mm
        return (self.content_width_mm - gutters) / column_count

    def span_width_mm(self, column_count: int, column_span: int) -> float:
        cw = self.column_width_mm(column_count)
        return cw * column_span + self.gutter_mm * max(0, column_span - 1)

    def slot_height_mm(self, page: TemplatePage, slot: StorySlot) -> float:
        # Convert normalized template coordinates into physical content height.
        normalized_page_h = max(1e-9, page.content_bottom - page.content_top)
        slot_fraction = (slot.bottom - slot.top) / normalized_page_h
        return self.content_height_mm * slot_fraction
