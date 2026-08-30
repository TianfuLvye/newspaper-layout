# Architecture — V0.3

```text
                        Template ZIP
                            |
                            v
                    +----------------+
                    | TemplateParser |
                    +--------+-------+
                             |
                             v
                    Template / StorySlot
                             |
                             |
Article JSON                 |
    |                        |
    v                        v
+----------------+    +--------------------+
| Markdown/image |    | Template features  |
| content        |    | (derived, no hand  |
+-------+--------+    | annotation needed) |
        |             +--------------------+
        |
        +------------------------------+
                                       |
                                       v
                        +------------------------------+
                        | story_article_html()         |
                        | shared semantic HTML         |
                        +--------------+---------------+
                                       |
                              shared NEWSPAPER_CSS
                                       |
                  +--------------------+-------------------+
                  |                                        |
                  v                                        v
      +---------------------------+             +-----------------------+
      | ChromiumArticleMeasurer   |             | HTMLNewspaperRenderer |
      | natural DOM height        |             | fixed A3 story slots  |
      +-------------+-------------+             +-----------+-----------+
                    |                                           |
                    v                                           v
              SlotMatcher                              newspaper.html
                    |
                    v
              LayoutOptimizer
                    |
                    v
              LayoutPlan JSON
```

## Critical invariant

**Measurement and rendering share the same article HTML and CSS.**

This prevents the optimizer from selecting a layout using one typography model and then
rendering with a different one.

## `chromium_measure.py`

- Finds Chromium from `CHROMIUM_PATH` or common executable names
- Launches one browser and reuses one page
- Uses a 100mm DOM probe to measure actual CSS px/mm
- Waits for document fonts and images
- Measures:
  - total story natural height
  - headline height
  - body height
  - media height
  - headline line count
- Caches by article content + geometry + visual treatment

## `html_components.py`

Single source of truth for:

- Markdown → escaped HTML
- image geometry / embedding
- story semantic structure
- headline scales
- body columns
- Markdown heading typography
- top/left/right/middle image rules
- print CSS

## `renderer.py`

Converts normalized template geometry to A3 millimetres.

Horizontal:
- discrete newspaper columns
- fixed gutters

Vertical:
- continuous normalized template coordinates
- mapped directly into physical content height

The renderer keeps story slots fixed to the selected template. Natural story content is
placed inside those slots. Browser JS marks slots whose natural height exceeds the slot.

## `optimizer.py`

Current backend remains beam search + exact unique page assignment.

The measurer is injectable. Therefore the same optimizer can run with:

- fast approximate measurement
- exact Chromium measurement

A future CP-SAT backend can use the same `SlotMatcher` / measurement API.

## Next major modules

### ContinuationAllocator
Turns `predicted_splits` into real page/slot reservations.

### DOMSplitter
Uses Chromium ranges and paragraph/heading boundaries to split article content at an exact
height without cutting a heading away from its following paragraph.

### ElasticTemplateSolver
Allows horizontal template boundaries to move continuously within an allowed range.

### Print/PDF pipeline
Chromium print output can be added once continuation flow is real and stable.


## V0.3 scoring priorities

### Page density

`SlotMatcher` penalizes local underfill. `LayoutOptimizer` then performs a second,
area-based page-level check using Chromium's `occupied_area_mm2`.

This two-level design is intentional:

- slot cost prevents obviously wrong article/slot pairings;
- page cost prevents several individually tolerable gaps from adding up to an empty page.

### Continuation

`ContinuationPolicy` is a shared invariant.

Current predictive optimizer:
- non-linear base continuation severity;
- extra cost for same-page avoidable continuation.

Future `ContinuationAllocator`:
- must reuse exactly the same policy;
- should add a real continuation only after comparing an unsplit re-layout;
- should prefer one continuation over repeated fragmentation.

This prevents "下转" from becoming an easy escape hatch for the packing algorithm.
