"""
rss_feeder.py — RSS 送饭器 (持续语料源) ★ v3.7

用户想法: RSS 每天给她送饭 — 语料自动更新, 不用手动找书
  抓 RSS → 解析 (标准库 xml, 零依赖) → 去重 → 喂语料管道

喂料 (跟喂书一样):
  标题+摘要 → language_traces (语言接触史 → 骨架池长肉)
  spread_write (联想增长)
  → 配合好奇心引擎: 新词 → 概念缺口 → 她主动去学

网络: 绕过环境代理直连 (沙盒代理端口常未启动) + 浏览器 UA
"""

import time
import urllib.request
import xml.etree.ElementTree as ET

SOURCES = [
    {"name": "少数派", "url": "https://sspai.com/feed"},
    {"name": "阮一峰博客", "url": "https://www.ruanyifeng.com/blog/atom.xml"},
    {"name": "BBC中文", "url": "https://feeds.bbci.co.uk/zhongwen/simp/rss.xml"},
    {"name": "科学网", "url": "http://news.sciencenet.cn/xml/sciencenet_news.xml"},
]

_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
       "AppleWebKit/537.36 AsteriaMind/3.7")


class RSSFeeder:
    """RSS 送饭器: 抓取 → 解析 → 去重 → 喂语料"""

    def __init__(self, star_map=None, db="asteriamind.db"):
        self.star_map = star_map
        self._conn = None
        self._db = db

    def _get_conn(self):
        import sqlite3
        if self._conn is None:
            self._conn = sqlite3.connect(self._db)
            self._conn.execute(
                "CREATE TABLE IF NOT EXISTS rss_seen("
                "url TEXT PRIMARY KEY, ts REAL)")
        return self._conn

    # ── 抓取 ──
    def fetch(self, url: str, timeout: int = 12) -> bytes:
        opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({}))  # 绕过环境代理
        req = urllib.request.Request(url, headers={"User-Agent": _UA})
        return opener.open(req, timeout=timeout).read()

    # ── 解析 (RSS 2.0 + Atom, 标准库) ──
    def parse(self, data: bytes) -> list:
        root = ET.fromstring(data)
        items = []
        for item in root.iter("item"):
            title = (item.findtext("title") or "").strip()
            link = (item.findtext("link") or "").strip()
            desc = (item.findtext("description") or "").strip()
            if title:
                items.append((title, link, desc))
        if not items:
            ns = "{http://www.w3.org/2005/Atom}"
            for entry in root.iter(ns + "entry"):
                title = (entry.findtext(ns + "title") or "").strip()
                le = entry.find(ns + "link")
                link = le.get("href") if le is not None else ""
                desc = (entry.findtext(ns + "summary") or "").strip()
                if title:
                    items.append((title, link or "", desc))
        return items

    # ── 喂料 ──
    def feed(self, max_items: int = 20) -> dict:
        """抓所有源 → 去重 → 喂语料管道"""
        stats = {"sources": 0, "fetched": 0, "new": 0,
                 "dup": 0, "errors": 0}
        for src in SOURCES:
            try:
                data = self.fetch(src["url"])
                items = self.parse(data)
                stats["sources"] += 1
                stats["fetched"] += len(items)
                for title, link, desc in items[:max_items]:
                    if not link or self._seen(link):
                        stats["dup"] += 1
                        continue
                    self._mark_seen(link)
                    text = f"{title}。{desc[:200]}"
                    if self.star_map:
                        self.star_map.spread_write(text)
                    self._save_sentence(text, title)
                    stats["new"] += 1
            except Exception as e:
                stats["errors"] += 1
                print(f"  ✗ {src['name']}: {str(e)[:60]}")
        return stats

    def _save_sentence(self, text: str, title: str):
        """标题+摘要 → language_traces (语言接触史)"""
        c = self._get_conn()
        c.execute(
            "INSERT INTO language_traces(sentence, subj, pred, obj, "
            "timestamp, sentence_type) VALUES (?,?,?,?,?,?)",
            (text[:500], title[:50], "", "", time.time(), "rss_feed"))
        c.commit()

    def _seen(self, url: str) -> bool:
        return self._get_conn().execute(
            "SELECT 1 FROM rss_seen WHERE url=?", (url,)).fetchone() is not None

    def _mark_seen(self, url: str):
        c = self._get_conn()
        c.execute("INSERT OR IGNORE INTO rss_seen VALUES (?,?)",
                  (url, time.time()))
        c.commit()


if __name__ == "__main__":
    import sys
    sys.path.insert(0, ".")
    from AsteriaMind.cognitive_star_map import CognitiveStarMap
    sm = CognitiveStarMap("asteriamind.db")
    feeder = RSSFeeder(star_map=sm)
    stats = feeder.feed(max_items=15)
    print(f"送饭完成: {stats}")
