from __future__ import annotations

from dataclasses import dataclass
import math
import re
import unicodedata
from typing import Iterable

from .geometry import PageGeometry
from .models import Article, ArticleProfile, ShapeCandidate, StorySlot, Template


PT_TO_MM = 25.4 / 72.0


@dataclass(frozen=True)
class TypographyConfig:
    body_font_pt: float = 9.0
    body_line_height: float = 1.18
    paragraph_gap_lines: float = 0.45
    title_sizes_pt: dict[str, float] = None
    heading_sizes_pt: dict[int, float] = None
    heading_line_heights: dict[int, float] = None
    title_line_height: float = 0.98
    title_margin_bottom_mm: float = 2.2
    section_gap_mm: float = 1.6
    char_width_factor_latin: float = 0.49
    char_width_factor_cjk: float = 0.94

    def __post_init__(self):
        if self.title_sizes_pt is None:
            object.__setattr__(self, "title_sizes_pt", {
                "small": 14.0,
                "medium": 19.0,
                "large": 27.0,
                "very_large": 38.0,
            })
        if self.heading_sizes_pt is None:
            object.__setattr__(self, "heading_sizes_pt", {
                1: 18.0,
                2: 15.0,
                3: 13.0,
                4: 11.5,
                5: 10.5,
                6: 9.8,
            })
        if self.heading_line_heights is None:
            object.__setattr__(self, "heading_line_heights", {
                1: 1.05,
                2: 1.08,
                3: 1.10,
                4: 1.12,
                5: 1.14,
                6: 1.16,
            })


class ArticleMeasurer:
    """
    Lightweight Markdown-aware estimator.

    It is deliberately isolated behind one class so V2 can replace this with a
    Chromium exact measurer while preserving the optimizer API.
    """

    def __init__(
        self,
        geometry: PageGeometry | None = None,
        typography: TypographyConfig | None = None,
    ):
        self.geometry = geometry or PageGeometry()
        self.typography = typography or TypographyConfig()

    def profile(
        self,
        article: Article,
        column_count: int,
        *,
        headline_weight: str = "medium",
        image_style: str | None = None,
        image_position: str | None = None,
    ) -> ArticleProfile:
        candidates: list[ShapeCandidate] = []
        for span in range(1, column_count + 1):
            width_mm = self.geometry.span_width_mm(column_count, span)
            measure = self.measure_at_width(
                article,
                width_mm,
                headline_weight=headline_weight,
                image_style=image_style,
                image_position=image_position,
            )
            candidates.append(
                ShapeCandidate(
                    width_columns=span,
                    width_mm=width_mm,
                    required_height_mm=measure["required_height_mm"],
                    title_height_mm=measure["title_height_mm"],
                    body_height_mm=measure["body_height_mm"],
                    image_height_mm=measure["image_height_mm"],
                    intrinsic_cost=measure["intrinsic_cost"],
                )
            )
        return ArticleProfile(article.id, column_count, candidates)

    def measure_for_slot(
        self,
        article: Article,
        template: Template,
        slot: StorySlot,
    ) -> dict[str, float]:
        width_mm = self.geometry.span_width_mm(
            template.page.column_count,
            slot.column_span,
        )
        return self.measure_at_width(
            article,
            width_mm,
            headline_weight=slot.headline_weight,
            image_style=slot.image_style,
            image_position=slot.image_position,
        )

    def measure_at_width(
        self,
        article: Article,
        width_mm: float,
        *,
        headline_weight: str = "medium",
        image_style: str | None = None,
        image_position: str | None = None,
    ) -> dict[str, float]:
        effective_text_width = width_mm
        image_height = 0.0

        if article.images and image_style and image_position in {"left", "right"}:
            frac = {"small": 0.34, "medium": 0.44, "large": 0.56}[image_style]
            effective_text_width = max(width_mm * (1 - frac) - 3.0, width_mm * 0.35)

        title_height = self._text_block_height(
            article.title,
            effective_text_width,
            font_pt=self.typography.title_sizes_pt.get(headline_weight, 19.0),
            line_height=self.typography.title_line_height,
            paragraph_gap=False,
        )
        if article.title:
            title_height += self.typography.title_margin_bottom_mm

        body_height = self._markdown_height(article.markdown, effective_text_width)

        if article.images and image_style:
            image_height = self._image_height(
                article,
                width_mm,
                image_style=image_style,
                image_position=image_position or "top",
            )
            if image_position in {"left", "right"}:
                # Side image shares vertical space with part of the article.
                body_height = max(body_height, image_height * 0.92)
                image_height *= 0.18  # residual vertical footprint / caption / separation
            else:
                body_height += image_height

        intrinsic = 0.0
        title_lines = self._line_count(
            article.title,
            effective_text_width,
            self.typography.title_sizes_pt.get(headline_weight, 19.0),
        )
        if headline_weight == "very_large" and title_lines > 4:
            intrinsic += (title_lines - 4) * 2.5
        if width_mm < 45 and len(article.markdown) > 3000:
            intrinsic += 4.0

        required = title_height + body_height + self.typography.section_gap_mm
        return {
            "required_height_mm": required,
            "title_height_mm": title_height,
            "body_height_mm": body_height,
            "image_height_mm": image_height,
            # Fast mode does not inspect DOM geometry, so use the bounding rectangle.
            # Chromium exact mode replaces this with title/body/media component area.
            "occupied_area_mm2": width_mm * required,
            "intrinsic_cost": intrinsic,
            "title_lines": float(title_lines),
        }

    def _markdown_height(self, markdown: str, width_mm: float) -> float:
        if not markdown.strip():
            return 0.0

        total = 0.0
        paragraphs = self._markdown_blocks(markdown)
        for kind, level, text in paragraphs:
            if not text.strip():
                continue
            if kind == "heading":
                pt = self.typography.heading_sizes_pt[level]
                lh = self.typography.heading_line_heights[level]
                total += self._text_block_height(
                    text,
                    width_mm,
                    font_pt=pt,
                    line_height=lh,
                    paragraph_gap=False,
                )
                total += self.typography.section_gap_mm
            elif kind == "list":
                total += self._text_block_height(
                    "• " + text,
                    width_mm,
                    font_pt=self.typography.body_font_pt,
                    line_height=self.typography.body_line_height,
                    paragraph_gap=True,
                )
            else:
                total += self._text_block_height(
                    text,
                    width_mm,
                    font_pt=self.typography.body_font_pt,
                    line_height=self.typography.body_line_height,
                    paragraph_gap=True,
                )
        return total

    def _markdown_blocks(self, markdown: str):
        blocks = []
        buffer = []

        def flush():
            nonlocal buffer
            if buffer:
                text = " ".join(x.strip() for x in buffer if x.strip())
                if text:
                    blocks.append(("paragraph", 0, text))
                buffer = []

        for raw in markdown.splitlines():
            line = raw.rstrip()
            if not line.strip():
                flush()
                continue

            m = re.match(r"^(#{1,6})\s+(.*)$", line)
            if m:
                flush()
                blocks.append(("heading", len(m.group(1)), m.group(2).strip()))
                continue

            lm = re.match(r"^\s*(?:[-*+]\s+|\d+[.)]\s+)(.*)$", line)
            if lm:
                flush()
                blocks.append(("list", 0, lm.group(1).strip()))
                continue

            # Ignore Markdown image syntax here; actual image dimensions come from metadata.
            if re.match(r"^\s*!\[[^\]]*\]\([^)]+\)\s*$", line):
                flush()
                continue

            buffer.append(self._strip_inline_markdown(line))

        flush()
        return blocks

    @staticmethod
    def _strip_inline_markdown(text: str) -> str:
        text = re.sub(r"`([^`]*)`", r"\1", text)
        text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
        text = re.sub(r"[*_~]+", "", text)
        return text

    def _text_block_height(
        self,
        text: str,
        width_mm: float,
        *,
        font_pt: float,
        line_height: float,
        paragraph_gap: bool,
    ) -> float:
        if not text:
            return 0.0
        lines = self._line_count(text, width_mm, font_pt)
        line_mm = font_pt * PT_TO_MM * line_height
        h = lines * line_mm
        if paragraph_gap:
            h += line_mm * self.typography.paragraph_gap_lines
        return h

    def _line_count(self, text: str, width_mm: float, font_pt: float) -> int:
        if not text:
            return 0
        font_mm = font_pt * PT_TO_MM
        capacity = max(width_mm / max(font_mm, 0.1), 1.0)
        units = 0.0
        for ch in text:
            if ch.isspace():
                units += 0.28
            elif unicodedata.east_asian_width(ch) in {"W", "F"}:
                units += self.typography.char_width_factor_cjk
            else:
                units += self.typography.char_width_factor_latin
        return max(1, math.ceil(units / capacity))

    def _image_height(
        self,
        article: Article,
        width_mm: float,
        *,
        image_style: str,
        image_position: str,
    ) -> float:
        # Use the first image as the principal image; extra images add a smaller residual footprint.
        img = article.images[0]
        if image_position in {"left", "right"}:
            width_frac = {"small": 0.34, "medium": 0.44, "large": 0.56}[image_style]
        else:
            width_frac = {"small": 0.52, "medium": 0.72, "large": 0.96}[image_style]

        display_width = max(10.0, width_mm * width_frac)
        raw_height = display_width / img.aspect_ratio

        # Newspaper crops are common. Avoid absurd portrait-image expansion.
        max_ratio = {"small": 0.28, "medium": 0.42, "large": 0.62}[image_style]
        max_height = width_mm * max_ratio
        main_height = min(raw_height, max_height)

        extra = 0.0
        for extra_img in article.images[1:3]:
            extra += min(width_mm * 0.20 / extra_img.aspect_ratio, width_mm * 0.16)

        return main_height + extra
