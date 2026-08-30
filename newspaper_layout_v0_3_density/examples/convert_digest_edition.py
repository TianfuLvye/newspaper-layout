"""Convert a 2026-*-am digest folder into newspaper-layout article JSON."""

from __future__ import annotations

import json
import re
import struct
from pathlib import Path


IMG_RE = re.compile(r"!\[([^\]]*)\]\((images/[^)]+)\)")
STRIP_LINE_RE = re.compile(
    r"^(读完再打点:|原文地址|相关报道\(已折叠\)|\*\*相关报道)",
)
SECTION_FILES = {
    "headline": "01_headline.md",
    "hotlist": "02_hotlist.md",
    "deepread": "03_deepread.md",
    "oral": "04_oral.md",
    "subscribe": "06_subscribe.md",
    "critical": "07_critical.md",
    "health": "99_health.md",
}


def normalize_title(title: str) -> str:
    return re.sub(r"\s+", "", title).replace("“", '"').replace("”", '"').replace("，", ",")


def image_size(path: Path) -> tuple[int, int]:
    data = path.read_bytes()
    if data[:8] == b"\x89PNG\r\n\x1a\n" and len(data) >= 24:
        width, height = struct.unpack(">II", data[16:24])
        return int(width), int(height)
    if data[:2] == b"\xff\xd8":
        i = 2
        while i + 9 < len(data):
            if data[i] != 0xFF:
                break
            marker = data[i + 1]
            if marker in {0xC0, 0xC1, 0xC2}:
                height, width = struct.unpack(">HH", data[i + 5 : i + 9])
                return int(width), int(height)
            length = struct.unpack(">H", data[i + 2 : i + 4])[0]
            i += 2 + length
    return 1600, 900


def parse_item(path: Path) -> dict | None:
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    title = ""
    if lines and lines[0].startswith("# "):
        title = lines[0][2:].strip()
        lines = lines[1:]
    while lines and not lines[0].strip():
        lines = lines[1:]
    if lines and lines[0].startswith(">"):
        lines = lines[1:]
        while lines and lines[0].startswith(">"):
            lines = lines[1:]
        while lines and not lines[0].strip():
            lines = lines[1:]

    body_lines: list[str] = []
    images: list[dict] = []
    for raw in lines:
        if STRIP_LINE_RE.match(raw.strip()):
            continue
        if raw.strip().startswith("原文地址"):
            continue
        match = IMG_RE.search(raw)
        if match:
            images.append({"alt": match.group(1), "rel": match.group(2)})
            continue
        if raw.strip() == "---":
            continue
        body_lines.append(raw)

    body = "\n".join(body_lines).strip()
    body = re.sub(r"\n{3,}", "\n\n", body)
    if not title or len(body) < 40:
        return None
    return {"title": title, "markdown": body, "images": images, "source": path.name}


def collect_section_images(edition: Path) -> dict[str, list[dict]]:
    mapping: dict[str, list[dict]] = {}
    heading_re = re.compile(r"^## (?:F\d+ · )?(.+)$")
    for name in SECTION_FILES.values():
        path = edition / name
        if not path.exists():
            continue
        current = None
        for line in path.read_text(encoding="utf-8").splitlines():
            heading = heading_re.match(line)
            if heading:
                current = normalize_title(heading.group(1).strip())
                mapping.setdefault(current, [])
                continue
            if current is None:
                continue
            match = IMG_RE.search(line)
            if match:
                mapping[current].append({"alt": match.group(1), "rel": match.group(2)})
    return mapping


def infer_section(title: str, ranking: dict[str, dict], file_hint: str) -> str:
    key = normalize_title(title)
    if key in ranking:
        return ranking[key]["section"]
    for ranked_title, item in ranking.items():
        if ranked_title in key or key in ranked_title:
            return item["section"]
    if "早餐" in title or "热榜" in title or "Top 20" in title:
        return "hotlist"
    if file_hint.startswith(("01", "02", "03")) and "海鲜" not in title:
        return "headline"
    return "subscribe"


def classify(section: str, markdown: str, score: float) -> tuple[str, float]:
    length = len(markdown)
    if section == "health":
        return "system_report", 0.18
    if section == "hotlist":
        if length > 2000:
            return "normal", 0.40
        return "brief", 0.28
    if section == "headline":
        kind = "long" if length > 1200 else ("brief" if length < 400 else "normal")
        return kind, min(0.97, 0.78 + score)
    if section == "deepread":
        kind = "long" if length > 2500 else "normal"
        return kind, min(0.86, 0.52 + score)
    if section == "critical":
        kind = "report" if length > 800 else "brief"
        return kind, min(0.72, 0.42 + score)
    if section == "oral":
        return "normal", 0.38
    if length < 350:
        return "brief", 0.32
    if length > 3500:
        return "long", min(0.74, 0.48 + score)
    return "normal", min(0.68, 0.40 + score)


def convert(edition: Path) -> list[dict]:
    ranking_raw = json.loads((edition / "ranking.json").read_text(encoding="utf-8"))
    ranking = {
        normalize_title(item["title"]): item
        for item in ranking_raw.get("items", [])
    }
    section_images = collect_section_images(edition)

    unique: dict[str, dict] = {}
    for path in sorted((edition / "items").glob("*.md")):
        parsed = parse_item(path)
        if parsed is None:
            continue
        key = normalize_title(parsed["title"])
        previous = unique.get(key)
        if previous is None or len(parsed["markdown"]) > len(previous["markdown"]):
            unique[key] = parsed

    lede = (edition / "00_lede.md").read_text(encoding="utf-8")
    lede_body = re.sub(r"^# .+\n+> .+\n+", "", lede).strip()
    unique[normalize_title("今日综述")] = {
        "title": "今日综述",
        "markdown": lede_body,
        "images": [],
        "source": "00_lede.md",
        "forced_section": "headline",
        "forced_kind": "brief",
        "forced_priority": 0.88,
    }

    hotlist = (edition / "02_hotlist.md").read_text(encoding="utf-8")
    hot_lines = []
    for line in hotlist.splitlines():
        if line.startswith("# ") or line.startswith(">"):
            continue
        hot_lines.append(line)
    unique[normalize_title("今日新上榜 Top 20")] = {
        "title": "今日新上榜 Top 20",
        "markdown": "\n".join(hot_lines).strip(),
        "images": [],
        "source": "02_hotlist.md",
        "forced_section": "hotlist",
    }

    health = (edition / "99_health.md").read_text(encoding="utf-8")
    health_lines = []
    for line in health.splitlines():
        if line.startswith("# "):
            continue
        if line.startswith("> "):
            continue
        health_lines.append(line)
    unique[normalize_title("系统体检")] = {
        "title": "系统体检",
        "markdown": "\n".join(health_lines).strip(),
        "images": [],
        "source": "99_health.md",
        "forced_section": "health",
    }

    articles = []
    for index, parsed in enumerate(unique.values(), start=1):
        title = parsed["title"]
        section = parsed.get("forced_section") or infer_section(title, ranking, parsed["source"])
        ranked = ranking.get(normalize_title(title), {})
        score = float(ranked.get("score", 0.2))
        kind, priority = classify(section, parsed["markdown"], score)
        if "forced_kind" in parsed:
            kind = parsed["forced_kind"]
        if "forced_priority" in parsed:
            priority = parsed["forced_priority"]

        images = parsed["images"] or section_images.get(normalize_title(title), [])
        payload_images = []
        seen = set()
        for image in images:
            rel = image["rel"]
            if rel in seen:
                continue
            seen.add(rel)
            src = edition / rel
            if not src.exists():
                continue
            width, height = image_size(src)
            payload_images.append({
                "width_px": width,
                "height_px": height,
                "src": str(src.resolve()),
                "alt": image["alt"] or title,
            })

        articles.append({
            "id": f"am{index:02d}",
            "title": title,
            "markdown": parsed["markdown"],
            "images": payload_images,
            "priority": round(priority, 3),
            "kind": kind,
            "metadata": {
                "section": section,
                "source": parsed["source"],
                "ranking_score": score,
            },
        })

    articles.sort(key=lambda a: (-a["priority"], a["id"]))
    for index, article in enumerate(articles, start=1):
        article["id"] = f"am{index:02d}"
    return articles


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    edition = root / "2026-08-28-am"
    articles = convert(edition)
    output = root / "examples" / "articles.2026-08-28-am.json"
    output.write_text(json.dumps(articles, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "output": str(output),
        "articles": len(articles),
        "with_images": sum(1 for a in articles if a["images"]),
        "kinds": {
            kind: sum(1 for a in articles if a["kind"] == kind)
            for kind in sorted({a["kind"] for a in articles})
        },
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
