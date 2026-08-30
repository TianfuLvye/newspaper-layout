# Real dataset audit: 2026-08-28-am.newspaper.ai.html

## Observed problems

- **15 pages / 26 unique stories.**
- **Template monotony:** `The_Guardian_-_2_Jul_2025_freemagazinespdf_com_p19` appears **9 / 15 pages (60%)**.
- Consecutive identical-template runs: p4–p8 (5 pages), p12–p14 (3 pages).
- **Front template is on page 15**, rather than page 1.
- **System report is on page 3**, despite being a tail-preferred item.
- Static plan marks **4** stories as overflow.
- Chromium confirms **4** real clipping overflows: am24@p11 (+503.0px), am07@p12 (+113.5px), am10@p13 (+366.3px), am15@p14 (+1008.9px).
- Markdown table syntax is rendered as a paragraph in **1** place(s), rather than as a table.
- At least **1** story has a structured headline followed by a near-duplicate body H1.
- Media: **15** media blocks, **0** real `<img>` elements, **15** placeholders.

## V0.4 fixes

1. Front-page template eligibility is now positional: front on page 1 only.
2. Template repetition has exact-repeat, consecutive-repeat, recent-window and structural-family penalties.
3. Ordering cost is inside page-assignment DP; report/long-article ordering rules now actually affect which story is selected for a page.
4. System/health reports receive a much stronger tail preference.
5. Markdown table plugin enabled; table CSS added.
6. Near-duplicate leading Markdown H1/H2 is removed when it repeats the structured title.
7. `DOMSplitter` measures candidate Markdown prefixes in Chromium and cuts at the largest legal block/sentence boundary.
8. `ContinuationAllocator` reflows the source page and the full suffix after every split, instead of freezing the source page.
9. Continuation head is pinned to the source page; tail cannot appear before the next page.
10. Final fragments carry explicit `下转第 X 版` / `上接第 X 版` links.
11. Renderer no longer uses a fake overflow-generated “下转”; residual overflow is labeled `排版溢出`, making allocator failures visible.
12. When fewer stories than template slots remain, the optimizer considers **all slot subsets**, not merely the first N slots.
13. Front templates render a real masthead in the large area that Guardian front-page references reserve for branding.

- Browser-measured visual utilization bottoms out at **13.2% on page 15**, which is the misplaced front template.
