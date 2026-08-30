# Newspaper Layout V1

A template-guided newspaper layout engine for a personal daily newspaper.

## V1 scope

This version implements:

- Template JSON parsing and validation
- Loading templates from folders or ZIP files
- Template feature extraction
- Markdown-aware article height estimation
- Width-dependent article shape profiles
- Slot/article fit scoring
- Image-position/style-aware scoring
- Headline-weight-aware scoring
- Template rating prior
- Single-page assignment optimization
- Multi-page beam-search planner
- Predicted continuation/split cost for overlong articles
- JSON layout-plan output

The current article measurer is deterministic and lightweight. It estimates typography
from Markdown structure and image dimensions. The architecture intentionally isolates
measurement behind `ArticleMeasurer`, so it can later be replaced by a Chromium-based
exact renderer without rewriting the optimizer.

## Template format

The current Guardian templates already match the expected V1 format:

```json
{
  "template_version": 1,
  "template_id": "guardian_p31",
  "source": {
    "publication": "The Guardian",
    "date": "2025-07-02",
    "page": 31,
    "reference_file": "reference.jpg"
  },
  "personal_rating": 5,
  "page": {
    "type": "interior",
    "column_count": 5,
    "content_left": 0.02,
    "content_right": 0.986,
    "content_top": 0.0,
    "content_bottom": 1.0
  },
  "stories": [
    {
      "id": "A",
      "column_start": 0,
      "column_span": 5,
      "top": 0.03,
      "bottom": 0.15,
      "role": "brief",
      "image_style": "large",
      "image_position": "left",
      "headline_weight": "very_large",
      "content_kind": "section_opener"
    }
  ]
}
```

`content_kind` is optional. Missing values default to `"article"`.

Accepted image positions in V1:

- `top`
- `left`
- `right`
- `middle`

Accepted image styles:

- `small`
- `medium`
- `large`

## Install

```bash
python -m pip install -e .
```

No third-party dependency is required for V1.

## Inspect a template ZIP

```bash
newspaper-layout inspect-templates /path/to/templates.zip
```

## Profile an article

Create an article JSON:

```json
{
  "id": "article_001",
  "title": "A long title",
  "markdown": "## Subheading\n\nBody text...",
  "images": [
    {"width_px": 1600, "height_px": 900}
  ],
  "priority": 0.8,
  "kind": "normal"
}
```

Then:

```bash
newspaper-layout profile-article article.json --columns 5
```

## Optimize a full issue

Prepare `articles.json` as a JSON array and run:

```bash
newspaper-layout optimize \
  --templates /path/to/templates.zip \
  --articles articles.json \
  --output layout_plan.json
```

Useful options:

```bash
--beam-width 8
--template-branching 10
--article-shortlist 14
--page-type interior
```

The output is a layout plan. It is not yet a final PDF renderer.

## Important V1 design choices

### Horizontal width is discrete
The page uses the template's 5 or 6 newspaper columns.

### Vertical measurement is continuous
All vertical sizes are calculated in millimetres and normalized template coordinates.

### Template slots are elastic
A template is treated as a visual skeleton. V1 scoring measures how well the article
fits the slot; later versions can explicitly move template boundaries.

### Overlong articles
V1 predicts a continuation count instead of physically splitting text. This creates
a meaningful split penalty and keeps the optimizer architecture ready for a real
continuation renderer.

## Next engineering step

Replace `ArticleMeasurer` with `ChromiumArticleMeasurer`:

1. Convert Markdown to semantic HTML.
2. Render at the exact slot width using the final CSS.
3. Read `scrollHeight`.
4. Convert CSS px to millimetres.
5. Cache by `(article_hash, width, headline_weight, image_style, image_position)`.

The rest of the project can stay unchanged.
