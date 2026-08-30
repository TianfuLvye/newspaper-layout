from __future__ import annotations

import base64
from difflib import SequenceMatcher
import html
import mimetypes
from pathlib import Path
import re
import unicodedata

import mistune

from .models import Article, ArticleImage


# Table support fixes report/system-health Markdown that previously rendered as pipes in <p>.
_MARKDOWN = mistune.create_markdown(
    escape=True,
    plugins=["table", "strikethrough", "task_lists"],
)


def _title_key(text: str) -> str:
    text = unicodedata.normalize("NFKC", text or "").lower()
    return "".join(ch for ch in text if ch.isalnum())


def strip_redundant_leading_heading(markdown: str, title: str) -> str:
    """
    Remove a leading Markdown H1/H2 if it merely repeats the external article title.

    Real feeds frequently contain the title twice: once in structured metadata and once
    as the first Markdown heading. Rendering both wastes space and looks accidental.
    """
    lines = (markdown or "").splitlines()
    first = None
    for i, line in enumerate(lines):
        if line.strip():
            first = i
            break
    if first is None:
        return markdown or ""

    m = re.match(r"^\s*#{1,2}\s+(.+?)\s*#*\s*$", lines[first])
    if not m:
        return markdown or ""

    heading = m.group(1).strip()
    a, b = _title_key(heading), _title_key(title)
    if not a or not b:
        return markdown or ""

    similarity = SequenceMatcher(None, a, b).ratio()
    if similarity < 0.84 and a not in b and b not in a:
        return markdown or ""

    del lines[first]
    # Remove one blank line left immediately after the deleted heading.
    if first < len(lines) and not lines[first].strip():
        del lines[first]
    return "\n".join(lines)


def markdown_to_html(markdown: str, *, title: str = "") -> str:
    markdown = strip_redundant_leading_heading(markdown or "", title)
    return _MARKDOWN(markdown)


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
        visual = (
            f'<div class="media-placeholder" aria-label="{alt}" '
            f'style="aspect-ratio:{ratio:.6f}"></div>'
        )

    figcaption = f"<figcaption>{caption}</figcaption>" if caption else ""
    return (
        f'<figure class="story-media {css_class}" style="--image-ar:{ratio:.6f}">'
        f"{visual}{figcaption}</figure>"
    )


def _continuation_header(article: Article) -> str:
    meta = article.metadata
    original_title = html.escape(str(meta.get("original_title") or article.title or ""))
    from_page = meta.get("continuation_from_page")
    from_text = f"上接第 {from_page} 版" if from_page else "续"
    return (
        '<header class="story-header continuation-header" data-measure-part="title">'
        f'<div class="continuation-kicker">{html.escape(from_text)}</div>'
        f'<h1>{original_title}</h1>'
        '</header>'
    )


def _normal_header(article: Article) -> str:
    title = html.escape(article.title or "")
    return (
        '<header class="story-header" data-measure-part="title">'
        f"<h1>{title}</h1>"
        "</header>"
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

    is_continuation = bool(article.metadata.get("continuation"))
    classes = [
        "story-content",
        f"headline-{headline_weight}",
        f"body-cols-{body_columns}",
    ]
    if is_continuation:
        classes.append("is-continuation")
    if image_style:
        classes.append(f"image-{image_style}")
    if image_position:
        classes.append(f"image-{image_position}")

    header = _continuation_header(article) if is_continuation else _normal_header(article)

    body_html = markdown_to_html(article.markdown, title=article.title)
    side_body_columns = max(1, body_columns - 1)
    body = (
        f'<div class="story-body" data-measure-part="body" '
        f'style="--body-columns:{body_columns};--side-body-columns:{side_body_columns}">{body_html}</div>'
    )

    media = ""
    if article.images and image_style and not is_continuation:
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
        main = body + media
    else:
        main = body

    to_page = article.metadata.get("continuation_to_page")
    continuation_footer = ""
    if to_page:
        text = "下转后版" if str(to_page) == "?" else f"下转第 {to_page} 版"
        continuation_footer = (
            f'<div class="continuation-footer">{html.escape(text)}</div>'
        )

    meta = ""
    if include_metadata:
        original_id = str(article.metadata.get("original_article_id") or article.id)
        fragment_index = int(article.metadata.get("fragment_index", 1))
        meta = (
            f'data-article-id="{html.escape(article.id, quote=True)}" '
            f'data-original-article-id="{html.escape(original_id, quote=True)}" '
            f'data-fragment-index="{fragment_index}" '
            f'data-article-kind="{html.escape(article.kind, quote=True)}" '
        )

    return (
        f'<article class="{" ".join(classes)}" {meta}>'
        f"{header}{main}{continuation_footer}</article>"
    )


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

.front-masthead {
  position: absolute;
  left: var(--page-margin-left);
  right: var(--page-margin-right);
  display: flex;
  flex-direction: column;
  justify-content: center;
  border-bottom: .8mm solid var(--ink);
  overflow: hidden;
}
.front-masthead-name {
  font: 800 58pt/.85 var(--serif);
  letter-spacing: -.055em;
}
.front-masthead-meta {
  margin-top: 3mm;
  display: flex;
  justify-content: space-between;
  font: 700 8pt/1 var(--sans);
  text-transform: uppercase;
  letter-spacing: .08em;
}

.story-slot {
  position: absolute;
  overflow: hidden;
  border-top: var(--rule) solid var(--ink);
}
.story-slot[data-role="lead"] { border-top-width: .45mm; }

.story-slot-inner {
  width: 100%;
  height: 100%;
  overflow: hidden;
  padding-top: 1.4mm;
  position: relative;
}

.story-content { width: 100%; color: var(--ink); }

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

.is-continuation .story-header h1 {
  font-size: 12.5pt !important;
  line-height: 1.05 !important;
  margin-bottom: 1.6mm;
  letter-spacing: -.01em;
}
.continuation-kicker {
  margin-bottom: .8mm;
  font: 800 7pt/1 var(--sans);
  letter-spacing: .08em;
  color: var(--muted);
}

.continuation-footer {
  width: max-content;
  max-width: 100%;
  margin: 1.4mm 0 0 auto;
  padding-top: .8mm;
  border-top: .22mm solid var(--ink);
  font: 800 7pt/1 var(--sans);
  letter-spacing: .04em;
}

.story-body {
  font-size: var(--body-size);
  line-height: var(--body-leading);
  column-count: var(--body-columns, 1);
  column-gap: var(--gutter);
  text-align: justify;
  hyphens: auto;
  orphans: 3;
  widows: 3;
}

.story-body p { margin: 0 0 1.55mm 0; break-inside: auto; }
.story-body p + p { text-indent: 1em; }

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

.story-body ul, .story-body ol { margin: 0 0 1.6mm 4mm; padding: 0; }
.story-body li { margin: 0 0 .7mm 0; break-inside: avoid-column; }
.story-body blockquote {
  margin: 1.5mm 0; padding-left: 2.5mm;
  border-left: .55mm solid var(--ink); font-style: italic;
}
.story-body code {
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: .88em;
}

/* Real Markdown tables, especially system-health reports. */
.story-body table {
  width: 100%;
  border-collapse: collapse;
  margin: 1.5mm 0 2mm;
  font: 6.7pt/1.15 var(--sans);
  text-align: left;
  break-inside: avoid;
}
.story-body th, .story-body td {
  border-bottom: .18mm solid #aaa;
  padding: .7mm .8mm;
  vertical-align: top;
}
.story-body th { font-weight: 800; border-bottom-color: var(--ink); }

.story-media { margin: 0; padding: 0; break-inside: avoid; }
.story-media img, .media-placeholder {
  display: block;
  width: 100%;
  object-fit: cover;
  background: linear-gradient(135deg, #d8d8d8, #eeeeee);
}
.story-media figcaption {
  margin-top: .8mm;
  color: var(--muted);
  font: 6.7pt/1.15 var(--sans);
}

.media-top, .media-middle { margin-bottom: 2mm; }
.image-top .media-top, .image-middle .media-middle { margin-left: auto; margin-right: auto; }
.image-small .media-top, .image-small .media-middle  { width: 52%; }
.image-medium .media-top, .image-medium .media-middle { width: 74%; }
.image-large .media-top, .image-large .media-middle  { width: 100%; }
.image-middle .media-middle { margin-top: 2mm; margin-bottom: 0; }

.story-side-layout {
  display: grid;
  column-gap: var(--gutter);
  align-items: start;
}
.story-side-layout.side-left  { grid-template-areas: "media body"; }
.story-side-layout.side-right { grid-template-areas: "body media"; }
.story-side-layout .story-media { grid-area: media; }
.story-side-layout .story-body  { grid-area: body; column-count: var(--side-body-columns, 1); }

.image-small .story-side-layout  { grid-template-columns: 30% 1fr; }
.image-medium .story-side-layout { grid-template-columns: 39% 1fr; }
.image-large .story-side-layout  { grid-template-columns: 48% 1fr; }

.story-slot.is-overflowing::after {
  content: "排版溢出";
  position: absolute;
  right: 0;
  bottom: 0;
  padding: .8mm 1.3mm;
  background: #fff;
  border: .22mm solid #900;
  color: #900;
  font: 800 6.5pt/1 var(--sans);
  letter-spacing: .06em;
}

.debug-layout .story-slot {
  outline: .35mm dashed rgba(180,0,0,.42);
  outline-offset: -.35mm;
}
.debug-layout .story-slot[data-fit="overflow"] { background: rgba(220,0,0,.035); }

.measure-host { margin: 0; padding: 0; background: white; }
.measure-probe { width: 100mm; height: 1mm; }
.measure-box { overflow: visible; background: white; }

@page { size: A3 portrait; margin: 0; }

@media print {
  html, body { background: white; }
  .newspaper-page { margin: 0; box-shadow: none; }
}
"""
