from __future__ import annotations

from dataclasses import dataclass
import html
import json
from pathlib import Path
from typing import Any

from .geometry import PageGeometry
from .html_components import NEWSPAPER_CSS, story_article_html
from .models import Article, LayoutPlan, PageAssignment, StorySlot, Template


@dataclass(frozen=True)
class RenderConfig:
    title: str = "Personal Newspaper"
    date_label: str = ""
    debug: bool = False
    embed_images: bool = True
    page_width_mm: float = 297.0
    page_height_mm: float = 420.0
    margin_top_mm: float = 12.0
    margin_right_mm: float = 12.0
    margin_bottom_mm: float = 12.0
    margin_left_mm: float = 12.0
    gutter_mm: float = 4.0


class HTMLNewspaperRenderer:
    def __init__(self, config: RenderConfig | None = None):
        self.config = config or RenderConfig()
        self.geometry = PageGeometry(
            width_mm=self.config.page_width_mm,
            height_mm=self.config.page_height_mm,
            margin_left_mm=self.config.margin_left_mm,
            margin_right_mm=self.config.margin_right_mm,
            margin_top_mm=self.config.margin_top_mm,
            margin_bottom_mm=self.config.margin_bottom_mm,
            gutter_mm=self.config.gutter_mm,
        )

    def render(
        self,
        plan: LayoutPlan,
        articles: list[Article],
        templates: list[Template],
    ) -> str:
        article_by_id = {a.id: a for a in articles}
        template_by_id = {t.template_id: t for t in templates}

        pages_html: list[str] = []
        for page_assignment in plan.pages:
            template = template_by_id[page_assignment.template_id]
            pages_html.append(
                self._render_page(page_assignment, template, article_by_id)
            )

        debug_class = "debug-layout" if self.config.debug else ""
        title = html.escape(self.config.title)
        css_vars = f"""
:root {{
  --paper-width: {self.config.page_width_mm}mm;
  --paper-height: {self.config.page_height_mm}mm;
  --page-margin-top: {self.config.margin_top_mm}mm;
  --page-margin-right: {self.config.margin_right_mm}mm;
  --page-margin-bottom: {self.config.margin_bottom_mm}mm;
  --page-margin-left: {self.config.margin_left_mm}mm;
  --gutter: {self.config.gutter_mm}mm;
}}
"""
        script = r"""
<script>
window.addEventListener("load", async () => {
  if (document.fonts && document.fonts.ready) await document.fonts.ready;
  for (const slot of document.querySelectorAll(".story-slot")) {
    const inner = slot.querySelector(".story-slot-inner");
    const content = slot.querySelector(".story-content");
    if (!inner || !content) continue;
    const overflow = content.getBoundingClientRect().height > inner.clientHeight + 1;
    slot.classList.toggle("is-overflowing", overflow);
    slot.dataset.fit = overflow ? "overflow" : "fit";
  }
});
</script>
"""
        return f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>
{NEWSPAPER_CSS}
{css_vars}
</style>
</head>
<body class="{debug_class}">
{''.join(pages_html)}
{script}
</body>
</html>
"""

    def render_to_file(
        self,
        output_path: str | Path,
        plan: LayoutPlan,
        articles: list[Article],
        templates: list[Template],
    ) -> Path:
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            self.render(plan, articles, templates),
            encoding="utf-8",
        )
        return output_path

    def _render_page(
        self,
        assignment: PageAssignment,
        template: Template,
        article_by_id: dict[str, Article],
    ) -> str:
        slot_by_id = {s.id: s for s in template.stories}
        rendered_slots: list[str] = []

        for score in assignment.assignments:
            slot = slot_by_id[score.slot_id]
            article = article_by_id[score.article_id]
            x, y, w, h = self._slot_rect_mm(template, slot)

            content = story_article_html(
                article,
                headline_weight=slot.headline_weight,
                image_style=slot.image_style,
                image_position=slot.image_position,
                body_columns=slot.column_span,
                embed_images=self.config.embed_images,
            )
            overflow_hint = "overflow" if score.predicted_splits else "fit"

            rendered_slots.append(
                f'<section class="story-slot" '
                f'data-role="{html.escape(slot.role)}" '
                f'data-slot-id="{html.escape(slot.id)}" '
                f'data-fit="{overflow_hint}" '
                f'style="left:{x:.4f}mm;top:{y:.4f}mm;'
                f'width:{w:.4f}mm;height:{h:.4f}mm">'
                f'<div class="story-slot-inner">{content}</div>'
                f'</section>'
            )

        page_no = assignment.page_index + 1
        date_label = html.escape(self.config.date_label)
        furniture = (
            '<div class="page-furniture">'
            f'<span>{html.escape(self.config.title)}</span>'
            f'<span>{date_label}</span>'
            f'<span>{page_no}</span>'
            '</div>'
        )

        masthead = ""
        if template.page.type == "front":
            first_y = min(
                (self._slot_rect_mm(template, s)[1] for s in template.stories),
                default=72.0,
            )
            top = 13.0
            height = max(24.0, first_y - top - 5.0)
            masthead = (
                f'<div class="front-masthead" style="top:{top:.2f}mm;height:{height:.2f}mm">'
                f'<div class="front-masthead-name">{html.escape(self.config.title)}</div>'
                '<div class="front-masthead-meta">'
                f'<span>{date_label}</span><span>PERSONAL EDITION</span>'
                '</div></div>'
            )

        return (
            f'<section class="newspaper-page" data-template-id="{html.escape(template.template_id)}" '
            f'data-page-type="{html.escape(template.page.type)}">'
            f"{furniture}{masthead}{''.join(rendered_slots)}</section>"
        )

    def _slot_rect_mm(
        self,
        template: Template,
        slot: StorySlot,
    ) -> tuple[float, float, float, float]:
        page = template.page
        cc = page.column_count

        content_x = self.geometry.margin_left_mm
        content_y = self.geometry.margin_top_mm
        content_w = self.geometry.content_width_mm
        content_h = self.geometry.content_height_mm

        # Respect the annotated content crop inside the reference page.
        crop_w = max(1e-9, page.content_right - page.content_left)
        crop_h = max(1e-9, page.content_bottom - page.content_top)

        # Horizontal positions use the discrete newspaper column system.
        column_w = self.geometry.column_width_mm(cc)
        x = content_x + slot.column_start * (column_w + self.geometry.gutter_mm)
        w = self.geometry.span_width_mm(cc, slot.column_span)

        # Vertical positions retain continuous normalized template coordinates.
        y_fraction = (slot.top - page.content_top) / crop_h
        h_fraction = (slot.bottom - slot.top) / crop_h
        y = content_y + y_fraction * content_h
        h = h_fraction * content_h

        return x, y, w, h


def layout_plan_from_dict(data: dict[str, Any]) -> LayoutPlan:
    from .models import PageAssignment, SlotScore

    pages = []
    for p in data.get("pages", []):
        assignments = [SlotScore(**x) for x in p.get("assignments", [])]
        pages.append(
            PageAssignment(
                template_id=p["template_id"],
                page_index=int(p["page_index"]),
                assignments=assignments,
                template_cost=float(p.get("template_cost", 0)),
                order_cost=float(p.get("order_cost", 0)),
                total_cost=float(p.get("total_cost", 0)),
                whitespace_cost=float(p.get("whitespace_cost", 0)),
                continuation_cost=float(p.get("continuation_cost", 0)),
                page_open_cost=float(p.get("page_open_cost", 0)),
                variety_cost=float(p.get("variety_cost", 0)),
                utilization=float(p.get("utilization", 1)),
            )
        )
    return LayoutPlan(
        pages=pages,
        total_cost=float(data.get("total_cost", 0)),
        unassigned_article_ids=list(data.get("unassigned_article_ids", [])),
        metadata=dict(data.get("metadata", {})),
    )
