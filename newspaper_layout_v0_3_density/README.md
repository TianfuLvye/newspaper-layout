# Newspaper Layout V0.3 — Dense Pages + Continuation Discipline

V0.3 builds on the Chromium exact-measurement renderer and changes the optimization
policy in two important ways:

1. **Visible blank page area is expensive.**
2. **`下转` is a last resort, and avoidable `下转` is much more expensive.**

## New in V0.3

### Visual occupied-area measurement

V0.2 mostly compared story height with slot height. That misses an important failure mode:
a side-image layout can have a tall bounding rectangle while a large region below the
image remains visibly empty.

Chromium now returns:

```text
occupied_area_mm2
```

computed from the real title/body/media DOM rectangles. Page utilization therefore sees:

- empty space below left/right images;
- narrow top/bottom images that leave visible side whitespace;
- underfilled body columns;
- completely unused template slots;
- unoccupied physical content area between story slots.

### Strong page-density cost

Defaults:

```text
interior target utilization: 90%
front target utilization:    70%
special target utilization:  80%

empty slot penalty:          140
page whitespace penalty:     700
severe whitespace penalty:   1400
page opening penalty:        35
```

A few percent of breathing room is still allowed. Large blank regions become rapidly
more expensive.

Each page in `LayoutPlan` now reports:

```json
{
  "utilization": 0.87,
  "whitespace_cost": 18.4,
  "page_open_cost": 35.0
}
```

### Continuation policy

The first continuation is already expensive; second/third continuations grow
non-linearly.

More importantly, an **avoidable continuation** is detected in the current page/template:
if the same article can fit unsplit in another active slot, assigning it to an overflowing
slot receives an additional penalty *inside the assignment DP*. That lets the optimizer
swap articles on the same page instead of creating an unnecessary `下转`.

The policy is centralized in:

```text
continuation.py / ContinuationPolicy
```

The future real `DOMSplitter + ContinuationAllocator` must call this same policy, so
implementing actual continuation will not accidentally make splits cheap.

### CLI tuning

All important density knobs are exposed:

```bash
--empty-slot-penalty 140
--page-utilization-target 0.90
--front-page-utilization-target 0.70
--special-page-utilization-target 0.80
--page-whitespace-penalty 700
--severe-whitespace-penalty 1400
--page-open-penalty 35
--split-weight 32
--slot-whitespace-weight 4
```

For your stated preference ("blank pages are intolerable"), start with the defaults.
If output is still too loose, raise `--page-whitespace-penalty` before changing font sizes.

---

Template-guided newspaper layout for a personal daily newspaper.

## What works now

### Template layer
- Reads the current Guardian template ZIP format directly
- Validates slot geometry
- Supports 5/6-column newspaper templates
- Supports `lead / secondary / normal / brief`
- Supports image positions: `top / left / right / middle`
- Supports image weights: `small / medium / large`
- Supports headline weights: `small / medium / large / very_large`
- Optional `content_kind`

### Article measurement
Two measurement backends are available:

1. `ArticleMeasurer`
   - lightweight approximation
   - useful for very fast experiments

2. `ChromiumArticleMeasurer`
   - launches real Chromium through Playwright
   - uses the same CSS component as the final renderer
   - measures a 100mm calibration probe in-browser
   - measures real DOM heights after fonts/images settle
   - renders Markdown headings as real H1–H6 elements
   - headlines span the whole story block
   - body text uses real CSS newspaper columns
   - image position/style is included in measurement
   - in-memory and optional disk cache

The exact backend is the preferred path for serious layout decisions.

### HTML renderer
- A3 portrait: 297 × 420 mm
- Physical margins and gutters in millimetres
- Continuous vertical template coordinates
- Discrete horizontal newspaper columns
- Absolute story-slot placement
- Shared article CSS with the exact measurer
- Print CSS (`@page size: A3 portrait`)
- Optional debug slot outlines
- Local images can be embedded as data URIs
- Missing image bytes still preserve geometry using the supplied width/height ratio
- Overflow is detected in the final browser DOM and marked `下转`

## Installation

```bash
python -m pip install -e .
```

Dependencies:

- `mistune`
- `playwright`

This project uses an installed Chromium binary. If it cannot be found automatically:

```bash
export CHROMIUM_PATH=/path/to/chromium
```

You do **not** have to use Playwright's bundled browser if a system Chromium exists.

## Article JSON

```json
{
  "id": "article_001",
  "title": "A long headline",
  "markdown": "## Subheading\n\nBody text...",
  "images": [
    {
      "width_px": 1600,
      "height_px": 900,
      "src": "images/photo.jpg",
      "alt": "Photo description",
      "caption": "Optional caption"
    }
  ],
  "priority": 0.8,
  "kind": "normal"
}
```

`src` is optional for measurement. If the bytes are unavailable, the renderer creates a
placeholder with the correct aspect ratio.

Relative image paths used through the CLI are resolved relative to the article JSON file.

## Inspect template ZIP

```bash
newspaper-layout inspect-templates guardian_templates.zip
```

## Exact shape profile

```bash
newspaper-layout profile-article article.json \
  --columns 5 \
  --headline-weight large \
  --image-style large \
  --image-position top \
  --exact \
  --cache .cache/measurements.json
```

## Optimize with exact Chromium measurement

```bash
newspaper-layout optimize \
  --templates guardian_templates.zip \
  --articles articles.json \
  --output layout.plan.json \
  --exact \
  --cache .cache/measurements.json
```

For early experiments with 20–30 articles, use a moderate search breadth first:

```bash
--beam-width 5 --template-branching 8 --article-shortlist 14
```

Then increase it after the scoring weights are stable.

## Render an existing plan

```bash
newspaper-layout render \
  --templates guardian_templates.zip \
  --articles articles.json \
  --plan layout.plan.json \
  --output newspaper.html \
  --title "My Daily" \
  --date-label "2026-08-30"
```

Use `--debug` to show template slot boundaries.

## Optimize + render in one command

```bash
newspaper-layout optimize-render \
  --templates guardian_templates.zip \
  --articles articles.json \
  --output newspaper.html \
  --plan-output newspaper.plan.json \
  --exact \
  --cache .cache/measurements.json \
  --title "My Daily" \
  --date-label "2026-08-30"
```

Open `newspaper.html` in Chromium. Printing from Chromium uses the embedded A3 print rules.

## Exact-measurement model

A multi-column story is no longer measured as one extremely wide line of text.

For a slot spanning `N` newspaper columns:

- headline: spans the entire slot
- ordinary body: `column-count: N`
- left/right image: image + text grid, text uses `N - 1` columns
- top image: image above the body
- `middle`: treated as a lower in-story image in V0.2

The exact measurer and renderer call the **same** `story_article_html()` component and
the **same** `NEWSPAPER_CSS`. This is deliberate: layout scoring and final rendering
must not disagree about typography.

## Current continuation behaviour

V0.2 predicts continuation/split cost during optimization and detects final DOM overflow.
An overflowing slot is visibly marked `下转`, so text is never silently assumed to fit.

The next major feature should be **real continuation allocation**:

1. reserve continuation slots/pages during optimization;
2. split article DOM at a valid paragraph/heading boundary;
3. emit `下转第 x 版`;
4. render only the remaining content in the continuation slot.

Until that is implemented, an overflow marker means the optimizer intentionally accepted
a continuation cost, but the remaining text is not yet flowed into another template slot.

## Tests

```bash
python -m pytest -q
```

Current test coverage includes:

- template validation
- approximate shape curve
- page optimizer assignment
- real Chromium measurement
- A3 HTML rendering
