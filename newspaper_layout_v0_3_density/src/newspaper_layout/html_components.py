from __future__ import annotations

import base64
import html
import mimetypes
from pathlib import Path
from typing import Iterable

import mistune

from .models import Article, ArticleImage


_MM_PER_IN = 25.4

# Escape raw HTML from article Markdown. The input is editorial content, not application HTML.
_MARKDOWN = mistune.create_markdown(escape=True)


def markdown_to_html(markdown: str) -> str:
    return _MARKDOWN(markdown or "")


def image_uri(image: ArticleImage, *, embed_local: bool = True) -> str | None:
    src = image.src
    if not src:
        return None
    if src.startswith(("data:", "http://", "https://", "file://")):
        return src

    path = Path(src).expanduser()
    if not path.exists():
        return src

    if not embed_local:
        return path.resolve().as_uri()

    mime, _ = mimetypes.guess_type(path.name)
    mime = mime or "application/octet-stream"
    payload = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{payload}"


def image_figure_html(
    image: ArticleImage,
    *,
    css_class: str,
    embed_local: bool = True,
) -> str:
    src = image_uri(image, embed_local=embed_local)
    ratio = image.aspect_ratio
    alt = html.escape(image.alt or "")
    caption = html.escape(image.caption or "")

    if src:
        visual = (
            f'<img src="{html.escape(src, quote=True)}" alt="{alt}" '
            f'style="aspect-ratio:{ratio:.6f}" loading="eager" decoding="sync">'
        )
    else:
        # Precise geometry still works without the image bytes.
        visual = (
            f'<div class="media-placeholder" aria-label="{alt}" '
            f'style="aspect-ratio:{ratio:.6f}"></div>'
        )

    figcaption = f"<figcaption>{caption}</figcaption>" if caption else ""
    return (
        f'<figure class="story-media {css_class}" style="--image-ar:{ratio:.6f}">'
        f"{visual}{figcaption}</figure>"
    )


def story_article_html(
    article: Article,
    *,
    headline_weight: str,
    image_style: str | None,
    image_position: str | None,
    body_columns: int,
    embed_images: bool = True,
    include_metadata: bool = True,
) -> str:
    body_columns = max(1, int(body_columns))
    image_position = image_position if image_position in {"top", "left", "right", "middle"} else None
    image_style = image_style if image_style in {"small", "medium", "large"} else None

    classes = [
        "story-content",
        f"headline-{headline_weight}",
        f"body-cols-{body_columns}",
    ]
    if image_style:
        classes.append(f"image-{image_style}")
    if image_position:
        classes.append(f"image-{image_position}")

    title = html.escape(article.title or "")
    header = (
        '<header class="story-header" data-measure-part="title">'
        f"<h1>{title}</h1>"
        "</header>"
    )

    body_html = markdown_to_html(article.markdown)
    side_body_columns = max(1, body_columns - 1)
    body = (
        f'<div class="story-body" data-measure-part="body" '
        f'style="--body-columns:{body_columns};--side-body-columns:{side_body_columns}">{body_html}</div>'
    )

    media = ""
    if article.images and image_style:
        media = image_figure_html(
            article.images[0],
            css_class=f"media-{image_position or 'top'} media-{image_style}",
            embed_local=embed_images,
        )

    if media and image_position in {"left", "right"}:
        main = (
            f'<div class="story-side-layout side-{image_position}">'
            f"{media}{body}</div>"
        )
    elif media and image_position == "top":
        main = media + body
    elif media and image_position == "middle":
        # In the template vocabulary "middle" usually behaves as a lower in-story image.
        main = body + media
    else:
        main = body

    meta = (
        f'data-article-id="{html.escape(article.id, quote=True)}" '
        f'data-article-kind="{html.escape(article.kind, quote=True)}" '
        if include_metadata else ""
    )

    return f'<article class="{" ".join(classes)}" {meta}>{header}{main}</article>'


NEWSPAPER_CSS = r"""
:root {
  --paper-width: 297mm;
  --paper-height: 420mm;
  --page-margin-top: 12mm;
  --page-margin-right: 12mm;
  --page-margin-bottom: 12mm;
  --page-margin-left: 12mm;
  --gutter: 4mm;
  --rule: 0.22mm;
  --ink: #111;
  --muted: #595959;
  --paper: #fff;
  --body-size: 9pt;
  --body-leading: 1.18;
  --serif: "Noto Serif CJK SC", "Noto Serif SC", "Source Han Serif SC",
           "Songti SC", "STSong", "Times New Roman", serif;
  --sans: "Noto Sans CJK SC", "Noto Sans SC", "Source Han Sans SC",
          "PingFang SC", "Helvetica Neue", Arial, sans-serif;
}

* { box-sizing: border-box; }

html, body {
  margin: 0;
  padding: 0;
  background: #e9e9e9;
  color: var(--ink);
}

body {
  font-family: var(--serif);
  text-rendering: geometricPrecision;
  -webkit-font-smoothing: antialiased;
}

.newspaper-page {
  position: relative;
  width: var(--paper-width);
  height: var(--paper-height);
  margin: 8mm auto;
  background: var(--paper);
  overflow: hidden;
  box-shadow: 0 1.5mm 5mm rgba(0,0,0,.16);
  page-break-after: always;
  break-after: page;
}

.page-furniture {
  position: absolute;
  left: var(--page-margin-left);
  right: var(--page-margin-right);
  top: 5mm;
  height: 5mm;
  display: flex;
  align-items: end;
  justify-content: space-between;
  font: 600 7pt/1 var(--sans);
  letter-spacing: .03em;
  border-bottom: var(--rule) solid var(--ink);
  padding-bottom: 1.2mm;
}

.story-slot {
  position: absolute;
  overflow: hidden;
  border-top: var(--rule) solid var(--ink);
}

.story-slot[data-role="lead"] {
  border-top-width: .45mm;
}

.story-slot-inner {
  width: 100%;
  height: 100%;
  overflow: hidden;
  padding-top: 1.4mm;
  position: relative;
}

.story-content {
  width: 100%;
  color: var(--ink);
}

.story-header h1 {
  margin: 0 0 2.1mm 0;
  font-family: var(--serif);
  font-weight: 780;
  letter-spacing: -.025em;
  text-wrap: balance;
  hyphens: auto;
}

.headline-small .story-header h1      { font-size: 14pt; line-height: 1.02; }
.headline-medium .story-header h1     { font-size: 19pt; line-height: .99; }
.headline-large .story-header h1      { font-size: 27pt; line-height: .96; }
.headline-very_large .story-header h1 { font-size: 38pt; line-height: .93; }

.story-body {
  font-size: var(--body-size);
  line-height: var(--body-leading);
  column-count: var(--body-columns, 1);
  column-gap: var(--gutter);
  column-rule: 0 solid transparent;
  text-align: justify;
  hyphens: auto;
  orphans: 3;
  widows: 3;
}

.story-body p {
  margin: 0 0 1.55mm 0;
  break-inside: auto;
}

.story-body p + p {
  text-indent: 1em;
}

.story-body h1,
.story-body h2,
.story-body h3,
.story-body h4,
.story-body h5,
.story-body h6 {
  font-family: var(--sans);
  font-weight: 760;
  line-height: 1.08;
  text-align: left;
  text-indent: 0;
  margin: 2.2mm 0 1.1mm;
  break-after: avoid-column;
  break-inside: avoid-column;
}

.story-body h1 { font-size: 16pt; }
.story-body h2 { font-size: 14pt; }
.story-body h3 { font-size: 12.5pt; }
.story-body h4 { font-size: 11pt; }
.story-body h5 { font-size: 10pt; }
.story-body h6 { font-size: 9.3pt; text-transform: uppercase; letter-spacing: .03em; }

.story-body ul,
.story-body ol {
  margin: 0 0 1.6mm 4mm;
  padding: 0;
}

.story-body li {
  margin: 0 0 .7mm 0;
  break-inside: avoid-column;
}

.story-body blockquote {
  margin: 1.5mm 0;
  padding-left: 2.5mm;
  border-left: .55mm solid var(--ink);
  font-style: italic;
}

.story-body code {
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: .88em;
}

.story-media {
  margin: 0;
  padding: 0;
  break-inside: avoid;
}

.story-media img,
.media-placeholder {
  display: block;
  width: 100%;
  object-fit: cover;
  background:
    linear-gradient(135deg, #d8d8d8, #eeeeee);
}

.story-media figcaption {
  margin-top: .8mm;
  color: var(--muted);
  font: 6.7pt/1.15 var(--sans);
}

/* Top / lower media: width encodes the template's image weight. */
.media-top,
.media-middle {
  margin-bottom: 2mm;
}
.image-top .media-top,
.image-middle .media-middle {
  margin-left: auto;
  margin-right: auto;
}
.image-small .media-top,
.image-small .media-middle  { width: 52%; }
.image-medium .media-top,
.image-medium .media-middle { width: 74%; }
.image-large .media-top,
.image-large .media-middle  { width: 100%; }

.image-middle .media-middle {
  margin-top: 2mm;
  margin-bottom: 0;
}

/* Side image uses a grid so measurement and final rendering are deterministic. */
.story-side-layout {
  display: grid;
  column-gap: var(--gutter);
  align-items: start;
}
.story-side-layout.side-left  { grid-template-areas: "media body"; }
.story-side-layout.side-right { grid-template-areas: "body media"; }
.story-side-layout .story-media { grid-area: media; }
.story-side-layout .story-body  { grid-area: body; column-count: max(1, calc(var(--body-columns) - 1)); }

.image-small .story-side-layout  { grid-template-columns: 30% 1fr; }
.image-medium .story-side-layout { grid-template-columns: 39% 1fr; }
.image-large .story-side-layout  { grid-template-columns: 48% 1fr; }

.story-slot.is-overflowing::after {
  content: "CONTINUED";
  position: absolute;
  right: 0;
  bottom: 0;
  padding: .8mm 1.3mm;
  background: var(--paper);
  border-top: var(--rule) solid var(--ink);
  border-left: var(--rule) solid var(--ink);
  font: 700 6.5pt/1 var(--sans);
  letter-spacing: .08em;
}

body:not(.debug-layout) .story-slot.is-overflowing::after {
  content: "下转";
}

.debug-layout .story-slot {
  outline: .35mm dashed rgba(180,0,0,.42);
  outline-offset: -.35mm;
}
.debug-layout .story-slot[data-fit="overflow"] {
  background: rgba(220,0,0,.035);
}

.measure-host {
  margin: 0;
  padding: 0;
  background: white;
}
.measure-probe {
  width: 100mm;
  height: 1mm;
}
.measure-box {
  overflow: visible;
  background: white;
}

@page {
  size: A3 portrait;
  margin: 0;
}

@media print {
  html, body { background: white; }
  .newspaper-page {
    margin: 0;
    box-shadow: none;
  }
}
"""
