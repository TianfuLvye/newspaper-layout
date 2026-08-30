from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any, Iterable


VALID_PAGE_TYPES = {"front", "interior", "back", "special"}
VALID_ROLES = {"lead", "secondary", "normal", "brief"}
VALID_IMAGE_STYLES = {"small", "medium", "large"}
VALID_IMAGE_POSITIONS = {"top", "left", "right", "middle"}
VALID_HEADLINE_WEIGHTS = {"small", "medium", "large", "very_large"}


@dataclass(frozen=True)
class ArticleImage:
    width_px: int
    height_px: int
    src: str | None = None
    alt: str = ""
    caption: str = ""

    @property
    def aspect_ratio(self) -> float:
        if self.height_px <= 0:
            return 1.0
        return max(0.05, self.width_px / self.height_px)


@dataclass
class Article:
    id: str
    title: str
    markdown: str
    images: list[ArticleImage] = field(default_factory=list)
    priority: float = 0.5
    kind: str = "normal"
    preferred_page_type: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @staticmethod
    def from_dict(data: dict[str, Any]) -> "Article":
        images = [
            img if isinstance(img, ArticleImage) else ArticleImage(
                width_px=int(img["width_px"]),
                height_px=int(img["height_px"]),
                src=img.get("src") or img.get("path") or img.get("url"),
                alt=str(img.get("alt", "")),
                caption=str(img.get("caption", "")),
            )
            for img in data.get("images", [])
        ]
        return Article(
            id=str(data["id"]),
            title=str(data.get("title", "")),
            markdown=str(data.get("markdown", "")),
            images=images,
            priority=float(data.get("priority", 0.5)),
            kind=str(data.get("kind", "normal")),
            preferred_page_type=data.get("preferred_page_type"),
            metadata=dict(data.get("metadata", {})),
        )


@dataclass(frozen=True)
class ShapeCandidate:
    width_columns: int
    width_mm: float
    required_height_mm: float
    title_height_mm: float
    body_height_mm: float
    image_height_mm: float
    intrinsic_cost: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ArticleProfile:
    article_id: str
    column_count: int
    candidates: list[ShapeCandidate]

    def for_width(self, width_columns: int) -> ShapeCandidate:
        for c in self.candidates:
            if c.width_columns == width_columns:
                return c
        raise KeyError(width_columns)

    def to_dict(self) -> dict[str, Any]:
        return {
            "article_id": self.article_id,
            "column_count": self.column_count,
            "candidates": [c.to_dict() for c in self.candidates],
        }


@dataclass(frozen=True)
class StorySlot:
    id: str
    column_start: int
    column_span: int
    top: float
    bottom: float
    role: str = "normal"
    image_style: str | None = None
    image_position: str | None = None
    headline_weight: str = "medium"
    content_kind: str = "article"
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def normalized_height(self) -> float:
        return self.bottom - self.top

    def to_dict(self) -> dict[str, Any]:
        result = {
            "id": self.id,
            "column_start": self.column_start,
            "column_span": self.column_span,
            "top": self.top,
            "bottom": self.bottom,
            "role": self.role,
            "headline_weight": self.headline_weight,
            "content_kind": self.content_kind,
        }
        if self.image_style is not None:
            result["image_style"] = self.image_style
        if self.image_position is not None:
            result["image_position"] = self.image_position
        result.update(self.extra)
        return result


@dataclass(frozen=True)
class TemplatePage:
    type: str
    column_count: int
    content_left: float = 0.0
    content_right: float = 1.0
    content_top: float = 0.0
    content_bottom: float = 1.0

    @property
    def normalized_width(self) -> float:
        return self.content_right - self.content_left

    @property
    def normalized_height(self) -> float:
        return self.content_bottom - self.content_top


@dataclass
class Template:
    template_id: str
    source: dict[str, Any]
    personal_rating: int
    page: TemplatePage
    stories: list[StorySlot]
    template_version: int = 1
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def story_count(self) -> int:
        return len(self.stories)

    def to_dict(self) -> dict[str, Any]:
        return {
            "template_version": self.template_version,
            "template_id": self.template_id,
            "source": self.source,
            "personal_rating": self.personal_rating,
            "page": asdict(self.page),
            "stories": [s.to_dict() for s in self.stories],
            **self.metadata,
        }


@dataclass(frozen=True)
class SlotScore:
    article_id: str
    slot_id: str
    total: float
    fit: float
    role: float
    image: float
    headline: float
    kind: float
    split: float
    predicted_splits: int
    required_height_mm: float
    slot_height_mm: float
    # Estimated/Chromium-measured visual occupancy inside the slot. This catches
    # internal voids such as a tall side-image grid with empty space below the image.
    occupied_area_mm2: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class PageAssignment:
    template_id: str
    page_index: int
    assignments: list[SlotScore]
    template_cost: float
    order_cost: float
    total_cost: float

    # V0.3 scoring diagnostics. Defaults preserve compatibility with V0.2 plans.
    whitespace_cost: float = 0.0
    continuation_cost: float = 0.0
    page_open_cost: float = 0.0
    utilization: float = 1.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "template_id": self.template_id,
            "page_index": self.page_index,
            "assignments": [x.to_dict() for x in self.assignments],
            "template_cost": self.template_cost,
            "order_cost": self.order_cost,
            "whitespace_cost": self.whitespace_cost,
            "continuation_cost": self.continuation_cost,
            "page_open_cost": self.page_open_cost,
            "utilization": self.utilization,
            "total_cost": self.total_cost,
        }


@dataclass
class LayoutPlan:
    pages: list[PageAssignment]
    total_cost: float
    unassigned_article_ids: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_cost": self.total_cost,
            "pages": [p.to_dict() for p in self.pages],
            "unassigned_article_ids": list(self.unassigned_article_ids),
        }
