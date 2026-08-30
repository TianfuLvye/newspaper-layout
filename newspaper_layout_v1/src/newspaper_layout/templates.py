from __future__ import annotations

import json
import zipfile
from pathlib import Path
from typing import Any, Iterable

from .models import (
    Template,
    TemplatePage,
    StorySlot,
    VALID_HEADLINE_WEIGHTS,
    VALID_IMAGE_POSITIONS,
    VALID_IMAGE_STYLES,
    VALID_PAGE_TYPES,
    VALID_ROLES,
)


class TemplateValidationError(ValueError):
    pass


class TemplateParser:
    """Load and validate V1 template JSON."""

    def parse_dict(self, data: dict[str, Any], *, origin: str = "<memory>") -> Template:
        problems: list[str] = []

        if int(data.get("template_version", 1)) != 1:
            problems.append("template_version must be 1")

        template_id = str(data.get("template_id", "")).strip()
        if not template_id:
            problems.append("template_id is required")

        page_data = data.get("page")
        if not isinstance(page_data, dict):
            problems.append("page must be an object")
            page_data = {}

        page_type = str(page_data.get("type", "interior"))
        if page_type not in VALID_PAGE_TYPES:
            problems.append(f"page.type={page_type!r} is not supported")

        column_count = int(page_data.get("column_count", 0) or 0)
        if column_count < 1:
            problems.append("page.column_count must be >= 1")

        content_left = float(page_data.get("content_left", 0.0))
        content_right = float(page_data.get("content_right", 1.0))
        content_top = float(page_data.get("content_top", 0.0))
        content_bottom = float(page_data.get("content_bottom", 1.0))

        if not (0 <= content_left < content_right <= 1):
            problems.append("page content_left/right must satisfy 0 <= left < right <= 1")
        if not (0 <= content_top < content_bottom <= 1):
            problems.append("page content_top/bottom must satisfy 0 <= top < bottom <= 1")

        stories_data = data.get("stories")
        if not isinstance(stories_data, list) or not stories_data:
            problems.append("stories must be a non-empty array")
            stories_data = []

        stories: list[StorySlot] = []
        ids: set[str] = set()

        for idx, raw in enumerate(stories_data):
            if not isinstance(raw, dict):
                problems.append(f"stories[{idx}] must be an object")
                continue

            sid = str(raw.get("id", "")).strip()
            if not sid:
                problems.append(f"stories[{idx}].id is required")
                sid = f"slot_{idx}"
            if sid in ids:
                problems.append(f"duplicate story id: {sid}")
            ids.add(sid)

            start = int(raw.get("column_start", -1))
            span = int(raw.get("column_span", 0))
            top = float(raw.get("top", -1))
            bottom = float(raw.get("bottom", -1))

            if start < 0 or start >= max(column_count, 1):
                problems.append(f"story {sid}: invalid column_start")
            if span < 1 or start + span > max(column_count, 1):
                problems.append(f"story {sid}: invalid column_span")
            if not (0 <= top < bottom <= 1):
                problems.append(f"story {sid}: invalid top/bottom")

            role = str(raw.get("role", "normal"))
            if role not in VALID_ROLES:
                problems.append(f"story {sid}: unsupported role {role!r}")

            image_style = raw.get("image_style")
            if image_style is not None and image_style not in VALID_IMAGE_STYLES:
                problems.append(f"story {sid}: unsupported image_style {image_style!r}")

            image_position = raw.get("image_position")
            if image_position is not None and image_position not in VALID_IMAGE_POSITIONS:
                problems.append(f"story {sid}: unsupported image_position {image_position!r}")

            headline_weight = str(raw.get("headline_weight", "medium"))
            if headline_weight not in VALID_HEADLINE_WEIGHTS:
                problems.append(f"story {sid}: unsupported headline_weight {headline_weight!r}")

            content_kind = str(raw.get("content_kind", "article"))

            known = {
                "id", "column_start", "column_span", "top", "bottom", "role",
                "image_style", "image_position", "headline_weight", "content_kind",
            }
            extra = {k: v for k, v in raw.items() if k not in known}

            stories.append(
                StorySlot(
                    id=sid,
                    column_start=start,
                    column_span=span,
                    top=top,
                    bottom=bottom,
                    role=role,
                    image_style=image_style,
                    image_position=image_position,
                    headline_weight=headline_weight,
                    content_kind=content_kind,
                    extra=extra,
                )
            )

        problems.extend(self._overlap_problems(stories))

        if problems:
            raise TemplateValidationError(
                f"{origin}: template validation failed:\n- " + "\n- ".join(problems)
            )

        known_top = {
            "template_version", "template_id", "source", "personal_rating", "page", "stories"
        }
        metadata = {k: v for k, v in data.items() if k not in known_top}

        return Template(
            template_version=int(data.get("template_version", 1)),
            template_id=template_id,
            source=dict(data.get("source", {})),
            personal_rating=int(data.get("personal_rating", 3)),
            page=TemplatePage(
                type=page_type,
                column_count=column_count,
                content_left=content_left,
                content_right=content_right,
                content_top=content_top,
                content_bottom=content_bottom,
            ),
            stories=stories,
            metadata=metadata,
        )

    def _overlap_problems(self, stories: list[StorySlot]) -> list[str]:
        problems: list[str] = []
        for i, a in enumerate(stories):
            for b in stories[i + 1:]:
                col_overlap = min(
                    a.column_start + a.column_span,
                    b.column_start + b.column_span,
                ) - max(a.column_start, b.column_start)
                vertical_overlap = min(a.bottom, b.bottom) - max(a.top, b.top)
                # Template annotations may differ by a few pixels. Only reject meaningful overlap.
                if col_overlap > 0 and vertical_overlap > 0.012:
                    problems.append(
                        f"stories {a.id} and {b.id} overlap "
                        f"(columns={col_overlap}, vertical={vertical_overlap:.4f})"
                    )
        return problems

    def load_file(self, path: str | Path) -> Template:
        path = Path(path)
        data = json.loads(path.read_text(encoding="utf-8"))
        return self.parse_dict(data, origin=str(path))

    def load_directory(self, path: str | Path) -> list[Template]:
        path = Path(path)
        templates: list[Template] = []
        for json_path in sorted(path.rglob("template.json")):
            templates.append(self.load_file(json_path))
        return templates

    def load_zip(self, path: str | Path) -> list[Template]:
        path = Path(path)
        templates: list[Template] = []
        with zipfile.ZipFile(path) as zf:
            names = sorted(n for n in zf.namelist() if n.endswith("/template.json"))
            for name in names:
                data = json.loads(zf.read(name).decode("utf-8"))
                templates.append(self.parse_dict(data, origin=f"{path}:{name}"))
        return templates

    def load(self, path: str | Path) -> list[Template]:
        path = Path(path)
        if path.is_dir():
            return self.load_directory(path)
        if path.suffix.lower() == ".zip":
            return self.load_zip(path)
        if path.name == "template.json" or path.suffix.lower() == ".json":
            return [self.load_file(path)]
        raise ValueError(f"Unsupported template source: {path}")
