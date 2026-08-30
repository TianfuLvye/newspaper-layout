from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import shutil
from typing import Any

from playwright.sync_api import sync_playwright

from .geometry import PageGeometry
from .html_components import NEWSPAPER_CSS, story_article_html
from .models import Article, ArticleProfile, ShapeCandidate, StorySlot, Template


@dataclass(frozen=True)
class ChromiumConfig:
    executable_path: str | None = None
    headless: bool = True
    timeout_ms: int = 8000
    cache_path: str | None = None


class ChromiumUnavailableError(RuntimeError):
    pass


class ChromiumArticleMeasurer:
    """
    Exact browser measurer used by both optimization and final HTML rendering.

    CSS absolute-length calibration is measured inside Chromium itself using a
    100 mm probe, avoiding assumptions about deviceScaleFactor.
    """

    def __init__(
        self,
        geometry: PageGeometry | None = None,
        config: ChromiumConfig | None = None,
    ):
        self.geometry = geometry or PageGeometry()
        self.config = config or ChromiumConfig()
        self._playwright = None
        self._browser = None
        self._page = None
        self._cache: dict[str, dict[str, float]] = {}
        self._cache_dirty = False
        self._load_cache()

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()

    def start(self) -> None:
        if self._page is not None:
            return

        executable = self.config.executable_path or os.environ.get("CHROMIUM_PATH")
        if not executable:
            for candidate in (
                "chromium", "chromium-browser", "google-chrome", "google-chrome-stable"
            ):
                executable = shutil.which(candidate)
                if executable:
                    break
        if not executable:
            raise ChromiumUnavailableError(
                "Chromium executable not found. Set CHROMIUM_PATH or install Chromium."
            )

        self._playwright = sync_playwright().start()
        try:
            self._browser = self._playwright.chromium.launch(
                headless=self.config.headless,
                executable_path=executable,
                args=[
                    "--no-sandbox",
                    "--disable-dev-shm-usage",
                    "--font-render-hinting=none",
                ],
            )
        except Exception:
            self._playwright.stop()
            self._playwright = None
            raise

        self._page = self._browser.new_page(
            viewport={"width": 1800, "height": 2200},
            device_scale_factor=1,
        )
        self._page.set_default_timeout(self.config.timeout_ms)

    def close(self) -> None:
        self._save_cache()
        if self._page is not None:
            self._page.close()
            self._page = None
        if self._browser is not None:
            self._browser.close()
            self._browser = None
        if self._playwright is not None:
            self._playwright.stop()
            self._playwright = None

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
            m = self.measure_at_width(
                article,
                width_mm,
                headline_weight=headline_weight,
                image_style=image_style,
                image_position=image_position,
                body_columns=span,
            )
            candidates.append(
                ShapeCandidate(
                    width_columns=span,
                    width_mm=width_mm,
                    required_height_mm=m["required_height_mm"],
                    title_height_mm=m["title_height_mm"],
                    body_height_mm=m["body_height_mm"],
                    image_height_mm=m["image_height_mm"],
                    intrinsic_cost=m["intrinsic_cost"],
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
            body_columns=slot.column_span,
        )

    def measure_at_width(
        self,
        article: Article,
        width_mm: float,
        *,
        headline_weight: str = "medium",
        image_style: str | None = None,
        image_position: str | None = None,
        body_columns: int = 1,
    ) -> dict[str, float]:
        key = self._cache_key(
            article,
            width_mm,
            headline_weight,
            image_style,
            image_position,
            body_columns,
        )
        if key in self._cache:
            return dict(self._cache[key])

        self.start()

        article_html = story_article_html(
            article,
            headline_weight=headline_weight,
            image_style=image_style,
            image_position=image_position,
            body_columns=body_columns,
            embed_images=True,
        )
        html_doc = f"""<!doctype html>
<html>
<head>
<meta charset="utf-8">
<style>
{NEWSPAPER_CSS}
html, body {{ margin:0; padding:0; background:#fff; }}
.measure-box {{
  width:{width_mm:.6f}mm;
  padding:0;
  margin:0;
}}
</style>
</head>
<body class="measure-host">
<div class="measure-probe" id="mm-probe"></div>
<div class="measure-box" id="measure-box">{article_html}</div>
</body>
</html>"""

        self._page.set_content(html_doc, wait_until="load")
        self._page.evaluate(
            """async () => {
                const imgs = [...document.images];
                await Promise.all(imgs.map(img => {
                    if (img.complete) return Promise.resolve();
                    return new Promise(resolve => {
                        const done = () => resolve();
                        img.addEventListener('load', done, {once:true});
                        img.addEventListener('error', done, {once:true});
                        setTimeout(done, 1200);
                    });
                }));
                if (document.fonts && document.fonts.ready) {
                    await document.fonts.ready;
                }
            }"""
        )

        result = self._page.evaluate(
            """() => {
                const probe = document.getElementById('mm-probe');
                const box = document.getElementById('measure-box');
                const story = box.querySelector('.story-content');
                const title = box.querySelector('[data-measure-part="title"]');
                const body = box.querySelector('[data-measure-part="body"]');
                const media = box.querySelector('.story-media');
                const pxPerMm = probe.getBoundingClientRect().width / 100.0;

                const mm = el => el ? el.getBoundingClientRect().height / pxPerMm : 0;
                const areaMm2 = el => {
                    if (!el) return 0;
                    const r = el.getBoundingClientRect();
                    return (r.width / pxPerMm) * (r.height / pxPerMm);
                };
                const cs = getComputedStyle(story);
                return {
                    required_height_mm: story.getBoundingClientRect().height / pxPerMm,
                    title_height_mm: mm(title),
                    body_height_mm: mm(body),
                    image_height_mm: mm(media),
                    occupied_area_mm2: areaMm2(title) + areaMm2(body) + areaMm2(media),
                    intrinsic_cost: 0,
                    title_lines: title ? Math.max(
                        1,
                        Math.round(
                            title.querySelector('h1').getBoundingClientRect().height /
                            parseFloat(getComputedStyle(title.querySelector('h1')).lineHeight)
                        )
                    ) : 0,
                    px_per_mm: pxPerMm
                };
            }"""
        )
        numeric = {k: float(v) for k, v in result.items()}
        self._cache[key] = numeric
        self._cache_dirty = True
        return dict(numeric)

    def _cache_key(
        self,
        article: Article,
        width_mm: float,
        headline_weight: str,
        image_style: str | None,
        image_position: str | None,
        body_columns: int,
    ) -> str:
        article_payload = {
            "id": article.id,
            "title": article.title,
            "markdown": article.markdown,
            "images": [
                {
                    "w": i.width_px, "h": i.height_px, "src": i.src,
                    "caption": i.caption, "alt": i.alt,
                }
                for i in article.images
            ],
        }
        payload = {
            "article": article_payload,
            "width_mm": round(width_mm, 5),
            "headline_weight": headline_weight,
            "image_style": image_style,
            "image_position": image_position,
            "body_columns": body_columns,
            "css_version": 3,
        }
        return hashlib.sha256(
            json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest()

    def _load_cache(self) -> None:
        if not self.config.cache_path:
            return
        path = Path(self.config.cache_path)
        if not path.exists():
            return
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                self._cache = {
                    str(k): {str(kk): float(vv) for kk, vv in v.items()}
                    for k, v in data.items()
                    if isinstance(v, dict)
                }
        except Exception:
            self._cache = {}

    def _save_cache(self) -> None:
        if not self.config.cache_path or not self._cache_dirty:
            return
        path = Path(self.config.cache_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(self._cache, ensure_ascii=False, separators=(",", ":")),
            encoding="utf-8",
        )
        self._cache_dirty = False
