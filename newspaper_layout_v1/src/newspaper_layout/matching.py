from __future__ import annotations

from dataclasses import dataclass
import math

from .geometry import PageGeometry
from .measure import ArticleMeasurer
from .models import Article, SlotScore, StorySlot, Template


@dataclass(frozen=True)
class MatchWeights:
    fit: float = 1.0
    role: float = 5.0
    image: float = 4.0
    headline: float = 2.5
    kind: float = 4.0
    split: float = 10.0
    template_rating: float = 1.5
    whitespace: float = 0.45


class SlotMatcher:
    def __init__(
        self,
        measurer: ArticleMeasurer | None = None,
        geometry: PageGeometry | None = None,
        weights: MatchWeights | None = None,
    ):
        self.geometry = geometry or PageGeometry()
        self.measurer = measurer or ArticleMeasurer(self.geometry)
        self.weights = weights or MatchWeights()

    def score(
        self,
        article: Article,
        template: Template,
        slot: StorySlot,
    ) -> SlotScore:
        measure = self.measurer.measure_for_slot(article, template, slot)
        required = measure["required_height_mm"]
        slot_height = self.geometry.slot_height_mm(template.page, slot)

        overflow = max(0.0, required - slot_height)
        underfill = max(0.0, slot_height - required)

        # Overflow is much more expensive than whitespace.
        fit_cost = (
            (overflow / max(slot_height, 1.0)) ** 2 * 120.0
            + (underfill / max(slot_height, 1.0)) ** 1.25 * self.weights.whitespace * 20.0
            + measure["intrinsic_cost"]
        )

        predicted_splits = 0
        if required > slot_height:
            predicted_splits = max(1, math.ceil(required / max(slot_height, 1.0)) - 1)
        split_cost = float(predicted_splits ** 2)

        role_cost = self._role_cost(article, slot)
        image_cost = self._image_cost(article, slot)
        headline_cost = self._headline_cost(article, slot, measure["title_lines"])
        kind_cost = self._kind_cost(article, slot)

        total = (
            self.weights.fit * fit_cost
            + self.weights.role * role_cost
            + self.weights.image * image_cost
            + self.weights.headline * headline_cost
            + self.weights.kind * kind_cost
            + self.weights.split * split_cost
        )

        return SlotScore(
            article_id=article.id,
            slot_id=slot.id,
            total=total,
            fit=fit_cost,
            role=role_cost,
            image=image_cost,
            headline=headline_cost,
            kind=kind_cost,
            split=split_cost,
            predicted_splits=predicted_splits,
            required_height_mm=required,
            slot_height_mm=slot_height,
        )

    def template_prior_cost(self, template: Template) -> float:
        rating = min(5, max(1, template.personal_rating))
        return (5 - rating) * self.weights.template_rating

    @staticmethod
    def _role_cost(article: Article, slot: StorySlot) -> float:
        p = min(1.0, max(0.0, article.priority))
        target = {
            "lead": 0.95,
            "secondary": 0.72,
            "normal": 0.50,
            "brief": 0.25,
        }[slot.role]
        cost = abs(p - target) * 2.0

        if article.kind == "brief" and slot.role == "brief":
            cost *= 0.25
        if article.kind in {"report", "system_report"} and slot.role == "lead":
            cost += 1.5
        return cost

    @staticmethod
    def _image_cost(article: Article, slot: StorySlot) -> float:
        has_image = bool(article.images)
        wants_image = slot.image_style is not None

        if wants_image and not has_image:
            return 2.2 if slot.image_style == "large" else 1.4
        if has_image and not wants_image:
            return 0.45
        if not has_image and not wants_image:
            return 0.0

        # Images exist and the slot supports an image.
        img = article.images[0]
        ar = img.aspect_ratio
        pos = slot.image_position or "top"
        cost = 0.0
        if pos in {"top", "middle"} and ar < 0.65:
            cost += 0.8
        if pos in {"left", "right"} and ar > 2.4:
            cost += 0.5
        return cost

    @staticmethod
    def _headline_cost(article: Article, slot: StorySlot, title_lines: float) -> float:
        target_max_lines = {
            "small": 4,
            "medium": 4,
            "large": 3,
            "very_large": 3,
        }[slot.headline_weight]
        cost = max(0.0, title_lines - target_max_lines) * 0.8

        # A very short title often benefits from a large display treatment.
        title_chars = len(article.title.strip())
        if slot.headline_weight == "very_large" and title_chars <= 42:
            cost *= 0.5
        return cost

    @staticmethod
    def _kind_cost(article: Article, slot: StorySlot) -> float:
        sk = slot.content_kind
        ak = article.kind

        if sk == "article":
            if ak in {"normal", "long", "report", "system_report", "brief"}:
                return 0.0
            return 0.3

        if sk == "section_opener":
            return 0.0 if ak in {"brief", "section_opener", "report"} else 0.9

        if sk == ak:
            return 0.0
        return 0.8
