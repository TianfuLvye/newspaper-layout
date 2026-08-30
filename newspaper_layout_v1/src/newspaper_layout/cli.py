from __future__ import annotations

import argparse
import json
from pathlib import Path

from .features import TemplateFeatureExtractor
from .measure import ArticleMeasurer
from .models import Article
from .optimizer import LayoutOptimizer, OptimizerConfig
from .templates import TemplateParser


def _load_articles(path: str | Path) -> list[Article]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(data, dict):
        data = [data]
    return [Article.from_dict(x) for x in data]


def cmd_inspect(args) -> int:
    parser = TemplateParser()
    extractor = TemplateFeatureExtractor()
    templates = parser.load(args.templates)
    payload = {
        "template_count": len(templates),
        "templates": [extractor.extract(t).to_dict() for t in templates],
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def cmd_profile(args) -> int:
    article = _load_articles(args.article)[0]
    measurer = ArticleMeasurer()
    profile = measurer.profile(
        article,
        args.columns,
        headline_weight=args.headline_weight,
        image_style=args.image_style,
        image_position=args.image_position,
    )
    print(json.dumps(profile.to_dict(), ensure_ascii=False, indent=2))
    return 0


def cmd_optimize(args) -> int:
    parser = TemplateParser()
    templates = parser.load(args.templates)
    articles = _load_articles(args.articles)

    optimizer = LayoutOptimizer(
        config=OptimizerConfig(
            beam_width=args.beam_width,
            template_branching=args.template_branching,
            article_shortlist=args.article_shortlist,
            max_pages=args.max_pages,
        )
    )
    plan = optimizer.optimize(
        articles,
        templates,
        page_type=args.page_type,
    )
    output = json.dumps(plan.to_dict(), ensure_ascii=False, indent=2)

    if args.output:
        Path(args.output).write_text(output + "\n", encoding="utf-8")
        print(args.output)
    else:
        print(output)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="newspaper-layout")
    sub = p.add_subparsers(dest="command", required=True)

    i = sub.add_parser("inspect-templates")
    i.add_argument("templates")
    i.set_defaults(func=cmd_inspect)

    pr = sub.add_parser("profile-article")
    pr.add_argument("article")
    pr.add_argument("--columns", type=int, default=5)
    pr.add_argument(
        "--headline-weight",
        choices=["small", "medium", "large", "very_large"],
        default="medium",
    )
    pr.add_argument("--image-style", choices=["small", "medium", "large"])
    pr.add_argument(
        "--image-position",
        choices=["top", "left", "right", "middle"],
    )
    pr.set_defaults(func=cmd_profile)

    o = sub.add_parser("optimize")
    o.add_argument("--templates", required=True)
    o.add_argument("--articles", required=True)
    o.add_argument("--output")
    o.add_argument("--page-type", choices=["front", "interior", "back", "special"])
    o.add_argument("--beam-width", type=int, default=8)
    o.add_argument("--template-branching", type=int, default=10)
    o.add_argument("--article-shortlist", type=int, default=14)
    o.add_argument("--max-pages", type=int, default=24)
    o.set_defaults(func=cmd_optimize)

    return p


def main() -> int:
    args = build_parser().parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
