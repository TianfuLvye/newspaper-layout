from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Callable

from .chromium_measure import ChromiumArticleMeasurer
from .geometry import PageGeometry
from .models import Article, StorySlot, Template


class DOMSplitError(RuntimeError):
    pass


@dataclass(frozen=True)
class DOMSplitterConfig:
    safety_mm: float = 2.2
    min_tail_chars: int = 180
    min_partial_chars: int = 80


@dataclass
class SplitResult:
    head: Article
    tail: Article | None
    head_height_mm: float
    slot_height_mm: float
    split_units: int
    used_partial_block: bool = False


class DOMSplitter:
    """
    Split Markdown using real Chromium layout.

    Primary breakpoints are Markdown block boundaries. Headings are paired with the
    following block so a section heading is not stranded at the bottom of a page.
    If one paragraph itself is too large, the fallback splits at sentence/line/space
    boundaries and binary-searches the largest prefix that fits.
    """

    def __init__(
        self,
        measurer: ChromiumArticleMeasurer,
        *,
        geometry: PageGeometry | None = None,
        config: DOMSplitterConfig | None = None,
    ):
        self.measurer = measurer
        self.geometry = geometry or PageGeometry()
        self.config = config or DOMSplitterConfig()

    def split_for_slot(
        self,
        article: Article,
        template: Template,
        slot: StorySlot,
        *,
        source_page_number: int,
    ) -> SplitResult:
        slot_height = (
            self.geometry.slot_height_mm(template.page, slot)
            - self.config.safety_mm
        )

        full = self.measurer.measure_for_slot(article, template, slot)
        if full["required_height_mm"] <= slot_height:
            return SplitResult(
                head=article,
                tail=None,
                head_height_mm=full["required_height_mm"],
                slot_height_mm=slot_height,
                split_units=0,
            )

        units = self._units(article.markdown)
        if not units:
            raise DOMSplitError(
                f"Article {article.id!r} overflows but has no splittable Markdown blocks"
            )

        def candidate(markdown: str) -> Article:
            return self._fragment_article(
                article,
                markdown=markdown,
                has_tail=True,
                source_page_number=source_page_number,
                tail=False,
            )

        def fits(markdown: str) -> tuple[bool, float]:
            probe = candidate(markdown)
            m = self.measurer.measure_for_slot(probe, template, slot)
            return m["required_height_mm"] <= slot_height, m["required_height_mm"]

        # Binary search the maximum number of whole units.
        lo, hi, best = 0, len(units) - 1, 0
        best_height = 0.0
        while lo <= hi:
            mid = (lo + hi) // 2
            n = mid + 1
            md = "\n\n".join(units[:n]).strip()
            ok, height = fits(md)
            if ok:
                best = n
                best_height = height
                lo = mid + 1
            else:
                hi = mid - 1

        used_partial = False
        if best == 0:
            head_piece, tail_piece, best_height = self._split_oversized_unit(
                units[0],
                fits,
            )
            head_units = [head_piece]
            tail_units = ([tail_piece] if tail_piece.strip() else []) + units[1:]
            used_partial = True
        else:
            head_units = units[:best]
            tail_units = units[best:]

        # Avoid a comically tiny continuation when moving one whole unit is possible.
        if (
            not used_partial
            and len(self._plainish("\n\n".join(tail_units))) < self.config.min_tail_chars
            and len(head_units) > 1
        ):
            tail_units.insert(0, head_units.pop())
            md = "\n\n".join(head_units).strip()
            ok, best_height = fits(md)
            if not ok:
                raise DOMSplitError("Failed to back off to a valid split")

        head_md = "\n\n".join(head_units).strip()
        tail_md = "\n\n".join(tail_units).strip()
        if not head_md or not tail_md:
            raise DOMSplitError(
                f"Could not produce two non-empty fragments for article {article.id}"
            )

        head = self._fragment_article(
            article,
            markdown=head_md,
            has_tail=True,
            source_page_number=source_page_number,
            tail=False,
        )
        tail = self._fragment_article(
            article,
            markdown=tail_md,
            has_tail=False,
            source_page_number=source_page_number,
            tail=True,
        )

        measured_head = self.measurer.measure_for_slot(head, template, slot)
        if measured_head["required_height_mm"] > slot_height + 0.4:
            raise DOMSplitError(
                f"Splitter invariant failed for {article.id}: "
                f"{measured_head['required_height_mm']:.1f}mm > {slot_height:.1f}mm"
            )

        return SplitResult(
            head=head,
            tail=tail,
            head_height_mm=measured_head["required_height_mm"],
            slot_height_mm=slot_height,
            split_units=len(head_units),
            used_partial_block=used_partial,
        )

    def _fragment_article(
        self,
        article: Article,
        *,
        markdown: str,
        has_tail: bool,
        source_page_number: int,
        tail: bool,
    ) -> Article:
        meta = dict(article.metadata)
        original_id = str(meta.get("original_article_id") or article.id)
        original_title = str(meta.get("original_title") or article.title)
        current_index = int(meta.get("fragment_index", 1))

        meta["original_article_id"] = original_id
        meta["original_title"] = original_title

        if tail:
            next_index = current_index + 1
            meta["fragment_index"] = next_index
            meta["continuation"] = True
            meta["continuation_from_page"] = source_page_number
            meta["continuation_source_page_index"] = source_page_number - 1
            meta.pop("continuation_to_page", None)
            # A re-split head may already be pinned. The new tail must not inherit
            # that pin, or the optimizer will try to place both fragments on the
            # same source page and then skip the tail on every later page.
            meta.pop("fixed_page_index", None)
            meta.pop("minimum_page_index", None)
            new_id = f"{original_id}::cont{next_index}"
            images = []
        else:
            meta["fragment_index"] = current_index
            if article.metadata.get("continuation"):
                meta["continuation"] = True
            if has_tail:
                # Real page number is patched by ContinuationAllocator at the end.
                meta["continuation_to_page"] = "?"
            else:
                meta.pop("continuation_to_page", None)
            new_id = article.id
            images = list(article.images)

        return Article(
            id=new_id,
            title=article.title,
            markdown=markdown,
            images=images,
            priority=article.priority,
            kind=article.kind,
            preferred_page_type=None if tail else article.preferred_page_type,
            metadata=meta,
        )

    def _units(self, markdown: str) -> list[str]:
        blocks = self._blocks(markdown)
        units: list[str] = []
        i = 0
        while i < len(blocks):
            block = blocks[i]
            if self._is_heading(block) and i + 1 < len(blocks):
                units.append(block + "\n\n" + blocks[i + 1])
                i += 2
            else:
                units.append(block)
                i += 1
        return units

    def _blocks(self, markdown: str) -> list[str]:
        lines = (markdown or "").splitlines()
        blocks: list[str] = []
        buf: list[str] = []
        in_fence = False

        def flush():
            nonlocal buf
            text = "\n".join(buf).strip()
            if text:
                blocks.append(text)
            buf = []

        for line in lines:
            if re.match(r"^\s*```", line):
                in_fence = not in_fence
                buf.append(line)
                continue
            if not in_fence and not line.strip():
                flush()
            else:
                buf.append(line)
        flush()
        return blocks

    @staticmethod
    def _is_heading(block: str) -> bool:
        first = block.lstrip().splitlines()[0] if block.strip() else ""
        return bool(re.match(r"^#{1,6}\s+", first))

    def _split_oversized_unit(
        self,
        unit: str,
        fits: Callable[[str], tuple[bool, float]],
    ) -> tuple[str, str, float]:
        # If a unit is "heading + paragraph", keep the heading in the head.
        parts = unit.split("\n\n", 1)
        fixed_prefix = ""
        splittable = unit
        if len(parts) == 2 and self._is_heading(parts[0]):
            fixed_prefix = parts[0].strip() + "\n\n"
            splittable = parts[1]

        positions = self._break_positions(splittable)
        if not positions:
            raise DOMSplitError("Oversized block has no safe sentence/space breakpoints")

        lo, hi, best = 0, len(positions) - 1, None
        best_height = 0.0
        while lo <= hi:
            mid = (lo + hi) // 2
            pos = positions[mid]
            head = fixed_prefix + splittable[:pos].rstrip()
            ok, height = fits(head)
            if ok:
                best = pos
                best_height = height
                lo = mid + 1
            else:
                hi = mid - 1

        if best is None or best < self.config.min_partial_chars:
            raise DOMSplitError(
                "Even the minimum safe prefix does not fit in the selected slot"
            )

        return (
            fixed_prefix + splittable[:best].rstrip(),
            splittable[best:].lstrip(),
            best_height,
        )

    def _break_positions(self, text: str) -> list[int]:
        positions: list[int] = []
        for m in re.finditer(r"[。！？!?；;：:\n]|(?<=\S)\s+", text):
            pos = m.end()
            if pos >= self.config.min_partial_chars:
                positions.append(pos)
        # Long CJK paragraphs without punctuation still get coarse safe fallback points.
        if not positions:
            positions = list(
                range(
                    self.config.min_partial_chars,
                    len(text),
                    max(60, self.config.min_partial_chars // 2),
                )
            )
        if len(text) > self.config.min_partial_chars:
            positions.append(len(text))
        return sorted(set(p for p in positions if 0 < p < len(text)))

    @staticmethod
    def _plainish(text: str) -> str:
        return re.sub(r"[#*_`>\[\]()|~-]+", "", text)
