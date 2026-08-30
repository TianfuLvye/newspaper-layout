# Architecture

## Data flow

```text
Article JSON / Markdown
        |
        v
ArticleMeasurer
        |
        +--> width-dependent ShapeProfile
        |
        v
SlotMatcher <---------------- TemplateParser
        |                           |
        |                           v
        |                    TemplateFeatureExtractor
        v
LayoutOptimizer
        |
        v
LayoutPlan JSON
```

## Modules

### `models.py`
Shared immutable-ish data structures.

### `templates.py`
Strict V1 template parser and validator.

### `geometry.py`
A3 physical geometry, newspaper columns, slot height conversion.

### `features.py`
Derived visual/template descriptors. All fields here are computed automatically;
template annotators do not need to enter them.

### `measure.py`
Current deterministic Markdown-aware measurement approximation.

The class boundary is intentional. A future Chromium implementation should preserve:

```python
measure_for_slot(article, template, slot) -> measurement dict
profile(article, column_count, ...) -> ArticleProfile
```

### `matching.py`
Defines the local cost function between one article and one template slot.

Current score components:

- fit / whitespace
- role
- image compatibility
- headline compatibility
- content kind
- predicted continuation count
- template personal-rating prior

### `optimizer.py`
Multi-page beam search. It chooses a template per page and a unique article
assignment within each page.

This is the V1 backend. Later, `CPSATLayoutOptimizer` can implement the same
public API using OR-Tools.

## Planned V2

1. Exact Chromium typography measurement
2. Explicit elastic movement of horizontal template boundaries
3. Real continuation blocks and continuation linking
4. CP-SAT backend
5. Cross-page visual variety penalty
6. Repeated-template penalty
7. Personal preference learning from daily A/B/C layout choices
8. PDF/HTML renderer
