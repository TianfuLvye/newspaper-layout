from __future__ import annotations

import argparse
import json
from pathlib import Path

from .chromium_measure import ChromiumArticleMeasurer, ChromiumConfig
from .continuation_allocator import ContinuationAllocator
from .dom_splitter import DOMSplitter
from .features import TemplateFeatureExtractor
from .matching import MatchWeights, SlotMatcher
from .measure import ArticleMeasurer
from .models import Article
from .optimizer import LayoutOptimizer, OptimizerConfig
from .renderer import HTMLNewspaperRenderer, RenderConfig, layout_plan_from_dict
from .templates import TemplateParser


def _load_articles(path: str | Path) -> list[Article]:
    path = Path(path)
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict):
        data = [data]

    for item in data:
        for image in item.get("images", []):
            src = image.get("src") or image.get("path")
            if src and not str(src).startswith(("http://", "https://", "data:", "file://")):
                candidate = Path(src)
                if not candidate.is_absolute():
                    resolved = (path.parent / candidate).resolve()
                    if resolved.exists():
                        image["src"] = str(resolved)
    return [Article.from_dict(x) for x in data]


def _load_plan(path: str | Path):
    return layout_plan_from_dict(
        json.loads(Path(path).read_text(encoding="utf-8"))
    )


def _optimizer_config(args) -> OptimizerConfig:
    return OptimizerConfig(
        beam_width=args.beam_width,
        template_branching=args.template_branching,
        article_shortlist=args.article_shortlist,
        max_pages=args.max_pages,
        empty_slot_penalty=args.empty_slot_penalty,
        target_page_utilization=args.page_utilization_target,
        front_page_utilization_target=args.front_page_utilization_target,
        special_page_utilization_target=args.special_page_utilization_target,
        page_whitespace_penalty=args.page_whitespace_penalty,
        severe_whitespace_penalty=args.severe_whitespace_penalty,
        page_open_penalty=args.page_open_penalty,
        template_reuse_penalty=args.template_reuse_penalty,
        consecutive_same_template_penalty=args.consecutive_template_penalty,
        recent_template_penalty=args.recent_template_penalty,
        template_family_penalty=args.template_family_penalty,
        early_report_penalty=args.report_penalty,
        continuation_delay_penalty=args.continuation_delay_penalty,
    )


def _match_weights(args) -> MatchWeights:
    return MatchWeights(
        split=args.split_weight,
        whitespace=args.slot_whitespace_weight,
    )


def _make_exact_stack(args):
    measurer = ChromiumArticleMeasurer(
        config=ChromiumConfig(
            executable_path=args.chromium_path,
            cache_path=args.cache,
        )
    )
    measurer.start()
    matcher = SlotMatcher(measurer=measurer, weights=_match_weights(args))
    optimizer = LayoutOptimizer(matcher=matcher, config=_optimizer_config(args))
    return measurer, matcher, optimizer


def _run_optimizer(args, templates, articles):
    if args.exact:
        measurer, matcher, optimizer = _make_exact_stack(args)
        try:
            return optimizer.optimize(articles, templates, page_type=args.page_type)
        finally:
            measurer.close()

    optimizer = LayoutOptimizer(
        matcher=SlotMatcher(weights=_match_weights(args)),
        config=_optimizer_config(args),
    )
    return optimizer.optimize(articles, templates, page_type=args.page_type)


def cmd_inspect(args) -> int:
    parser = TemplateParser()
    extractor = TemplateFeatureExtractor()
    templates = parser.load(args.templates)
    print(json.dumps({
        "template_count": len(templates),
        "templates": [extractor.extract(t).to_dict() for t in templates],
    }, ensure_ascii=False, indent=2))
    return 0


def cmd_profile(args) -> int:
    article = _load_articles(args.article)[0]
    if args.exact:
        with ChromiumArticleMeasurer(
            config=ChromiumConfig(
                executable_path=args.chromium_path,
                cache_path=args.cache,
            )
        ) as measurer:
            profile = measurer.profile(
                article,
                args.columns,
                headline_weight=args.headline_weight,
                image_style=args.image_style,
                image_position=args.image_position,
            )
    else:
        profile = ArticleMeasurer().profile(
            article,
            args.columns,
            headline_weight=args.headline_weight,
            image_style=args.image_style,
            image_position=args.image_position,
        )
    print(json.dumps(profile.to_dict(), ensure_ascii=False, indent=2))
    return 0


def cmd_optimize(args) -> int:
    templates = TemplateParser().load(args.templates)
    articles = _load_articles(args.articles)
    plan = _run_optimizer(args, templates, articles)
    output = json.dumps(plan.to_dict(), ensure_ascii=False, indent=2)
    if args.output:
        Path(args.output).write_text(output + "\n", encoding="utf-8")
        print(args.output)
    else:
        print(output)
    return 0


def cmd_render(args) -> int:
    templates = TemplateParser().load(args.templates)
    articles = _load_articles(args.articles)
    plan = _load_plan(args.plan)
    renderer = HTMLNewspaperRenderer(
        RenderConfig(
            title=args.title,
            date_label=args.date_label,
            debug=args.debug,
            embed_images=not args.link_images,
        )
    )
    print(renderer.render_to_file(args.output, plan, articles, templates))
    return 0


def cmd_optimize_render(args) -> int:
    templates = TemplateParser().load(args.templates)
    original_articles = _load_articles(args.articles)

    plan = _run_optimizer(args, templates, original_articles)
    render_articles = original_articles
    continuation_stats = None

    if not args.no_continuations:
        # DOM splitting always uses exact Chromium, even if the initial exploratory
        # optimizer was run in fast mode.
        measurer, matcher, optimizer = _make_exact_stack(args)
        try:
            splitter = DOMSplitter(measurer)
            allocation = ContinuationAllocator(optimizer, splitter).allocate(
                plan,
                original_articles,
                templates,
            )
            plan = allocation.plan
            render_articles = allocation.articles
            continuation_stats = {
                "splits": allocation.split_count,
                "fragments": allocation.fragment_count,
                "reflow_rounds": allocation.reflow_rounds,
            }
        finally:
            measurer.close()

    plan_path = (
        Path(args.plan_output)
        if args.plan_output
        else Path(args.output).with_suffix(".plan.json")
    )
    fragment_path = (
        Path(args.fragments_output)
        if args.fragments_output
        else Path(args.output).with_suffix(".fragments.json")
    )

    plan_path.write_text(
        json.dumps(plan.to_dict(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    fragment_path.write_text(
        json.dumps([a.to_dict() for a in render_articles], ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    renderer = HTMLNewspaperRenderer(
        RenderConfig(
            title=args.title,
            date_label=args.date_label,
            debug=args.debug,
            embed_images=not args.link_images,
        )
    )
    renderer.render_to_file(args.output, plan, render_articles, templates)

    print(json.dumps({
        "html": str(Path(args.output)),
        "plan": str(plan_path),
        "fragments": str(fragment_path),
        "pages": len(plan.pages),
        "unassigned": plan.unassigned_article_ids,
        "cost": plan.total_cost,
        "measurement": "chromium" if args.exact else "estimated+chromium-continuation",
        "continuation": continuation_stats,
    }, ensure_ascii=False, indent=2))
    return 0


def _add_optimizer_args(p):
    p.add_argument("--page-type", choices=["front", "interior", "back", "special"])
    p.add_argument("--beam-width", type=int, default=8)
    p.add_argument("--template-branching", type=int, default=10)
    p.add_argument("--article-shortlist", type=int, default=14)
    p.add_argument("--max-pages", type=int, default=32)

    p.add_argument("--empty-slot-penalty", type=float, default=140.0)
    p.add_argument("--page-utilization-target", type=float, default=0.90)
    p.add_argument("--front-page-utilization-target", type=float, default=0.70)
    p.add_argument("--special-page-utilization-target", type=float, default=0.80)
    p.add_argument("--page-whitespace-penalty", type=float, default=700.0)
    p.add_argument("--severe-whitespace-penalty", type=float, default=1400.0)
    p.add_argument("--page-open-penalty", type=float, default=35.0)

    p.add_argument("--split-weight", type=float, default=32.0)
    p.add_argument("--slot-whitespace-weight", type=float, default=4.0)
    p.add_argument("--continuation-delay-penalty", type=float, default=85.0)

    p.add_argument("--template-reuse-penalty", type=float, default=28.0)
    p.add_argument("--consecutive-template-penalty", type=float, default=135.0)
    p.add_argument("--recent-template-penalty", type=float, default=42.0)
    p.add_argument("--template-family-penalty", type=float, default=16.0)
    p.add_argument("--report-penalty", type=float, default=70.0)

    p.add_argument("--exact", action="store_true", help="Use Chromium exact measurement")
    p.add_argument("--chromium-path")
    p.add_argument("--cache", help="JSON cache for Chromium measurements")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="newspaper-layout")
    sub = p.add_subparsers(dest="command", required=True)

    i = sub.add_parser("inspect-templates")
    i.add_argument("templates")
    i.set_defaults(func=cmd_inspect)

    pr = sub.add_parser("profile-article")
    pr.add_argument("article")
    pr.add_argument("--columns", type=int, default=5)
    pr.add_argument("--headline-weight", choices=["small", "medium", "large", "very_large"], default="medium")
    pr.add_argument("--image-style", choices=["small", "medium", "large"])
    pr.add_argument("--image-position", choices=["top", "left", "right", "middle"])
    pr.add_argument("--exact", action="store_true")
    pr.add_argument("--chromium-path")
    pr.add_argument("--cache")
    pr.set_defaults(func=cmd_profile)

    o = sub.add_parser("optimize")
    o.add_argument("--templates", required=True)
    o.add_argument("--articles", required=True)
    o.add_argument("--output")
    _add_optimizer_args(o)
    o.set_defaults(func=cmd_optimize)

    r = sub.add_parser("render")
    r.add_argument("--templates", required=True)
    r.add_argument("--articles", required=True)
    r.add_argument("--plan", required=True)
    r.add_argument("--output", required=True)
    r.add_argument("--title", default="Personal Newspaper")
    r.add_argument("--date-label", default="")
    r.add_argument("--debug", action="store_true")
    r.add_argument("--link-images", action="store_true")
    r.set_defaults(func=cmd_render)

    e = sub.add_parser("optimize-render")
    e.add_argument("--templates", required=True)
    e.add_argument("--articles", required=True)
    e.add_argument("--output", required=True)
    e.add_argument("--plan-output")
    e.add_argument("--fragments-output")
    e.add_argument("--title", default="Personal Newspaper")
    e.add_argument("--date-label", default="")
    e.add_argument("--debug", action="store_true")
    e.add_argument("--link-images", action="store_true")
    e.add_argument("--no-continuations", action="store_true")
    _add_optimizer_args(e)
    e.set_defaults(func=cmd_optimize_render)

    return p


def main() -> int:
    args = build_parser().parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
