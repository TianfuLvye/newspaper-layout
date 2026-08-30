# 系统体检

> 生成于 2026-08-28 13:46 CST

**告警 2 项** —— 读报时请扫一眼。

- hotlist_weibo 过去 24h 全失败 · HTTPStatusError("Server error '500 Internal Server Error' for url 'http://127.0.0.1:6688/weibo'\nFor more information check: https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/500")
- 323 篇有正文的未读已积压 450h,该出报了

## 采集失败(24h 跑过但全挂)

这些网今天有跑、但一次都没成功。常见原因:上游挂了、页面改版、Cookie 过期。

- `hotlist_weibo` · runs=1 failed=1 · HTTPStatusError("Server error '500 Internal Server Error' for url 'http://127.0.0.1:6688/weibo'\nFor more information check: https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/500")

## 容量

- 数据库: 10.5 MB
- 未上报纸条目: 1624 · 最老 524.3h(含热榜标题)
- 有正文未读: 323 · 最老 450.3h

## 各网 24h

| collector | runs | ok | fail | new | last_ok |
|---|---:|---:|---:|---:|---|
| `hotlist_bilibili` | 1 | 1 | 0 | 38 | 2026-08-28T02:42:43 |
| `hotlist_douyin` | 1 | 1 | 0 | 43 | 2026-08-28T02:42:43 |
| `hotlist_thepaper` | 1 | 1 | 0 | 20 | 2026-08-28T02:42:44 |
| `hotlist_toutiao` | 1 | 1 | 0 | 50 | 2026-08-28T02:42:44 |
| `hotlist_weibo` ** | 1 | 0 | 1 | 0 | - |
| `hotlist_zhihu` | 1 | 1 | 0 | 29 | 2026-08-28T02:42:42 |
| `rss_bangumi_今日放送` | 2 | 2 | 0 | 16 | 2026-08-28T02:42:50 |
| `rss_thoughts_memo_回答` | 2 | 2 | 0 | 1 | 2026-08-28T02:42:44 |
| `rss_九边` | 3 | 3 | 0 | 12 | 2026-08-28T02:43:01 |
| `rss_人物` | 5 | 1 | 4 | 10 | 2026-08-28T02:43:01 |
| `rss_华尔街日报_世界新闻` | 2 | 2 | 0 | 0 | 2026-08-28T02:42:54 |
| `rss_华尔街日报_市场` | 2 | 2 | 0 | 0 | 2026-08-28T02:42:54 |
| `rss_华尔街日报_科技` | 2 | 2 | 0 | 0 | 2026-08-28T02:42:55 |
| `rss_华尔街见闻_全球` | 2 | 2 | 0 | 43 | 2026-08-28T02:42:56 |
| `rss_差评xpin` | 3 | 3 | 0 | 20 | 2026-08-28T02:43:01 |
| `rss_差评君_回答` | 2 | 2 | 0 | 0 | 2026-08-28T02:42:46 |
| `rss_知乎日报_早报` | 2 | 2 | 0 | 1 | 2026-08-28T02:42:48 |
| `rss_章北海的自然选择` | 4 | 4 | 0 | 0 | 2026-08-28T02:43:01 |
| `rss_辛庄课堂` | 4 | 1 | 3 | 10 | 2026-08-28T02:43:01 |

_`**` 全失败 · `·` 未调度 · `*` 产出骤降_
