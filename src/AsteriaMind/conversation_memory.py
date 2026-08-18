"""
ConversationMemory — AM 的长期对话上下文 (v3.2)

不用显存，用 SQLite + KG 做"检索式上下文"。

类比 LLM:
  - Transformer 注意力矩阵 → KG 关系查询 (相关度 = 置信度)
  - 长上下文窗口 → SQLite 全量历史 + 按话题检索
  - 自回归生成 → _process 用检索到的上下文影响解析路径
"""
import json, time, re
from typing import Optional
from AsteriaMind.knowledge_db import KnowledgeDB


class ConversationMemory:
    """
    永久对话记忆——不丢、可检索、有上下文。

    索引维度:
      1. 时间: 最近 N 轮对话
      2. 话题: 同一主题自动串联
      3. 关键词: KG 相似度检索
    """

    def __init__(self, db: KnowledgeDB, max_recent: int = 20):
        self.db = db
        self.max_recent = max_recent
        self._ensure_tables()

    def _ensure_tables(self):
        cur = self.db.conn.cursor()
        cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='conversation_log'")
        if not cur.fetchone():
            cur.executescript("""
                CREATE TABLE conversation_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    topic TEXT DEFAULT '',
                    timestamp REAL
                );
                CREATE INDEX idx_conv_session ON conversation_log(session_id);
                CREATE INDEX idx_conv_topic ON conversation_log(topic);
                CREATE INDEX idx_conv_time ON conversation_log(timestamp);
            """)
        # ★ v3.9 F13: 会话级上下文 — 滚动摘要/话题链/最近实体 (长对话不丢前文)
        cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='session_context'")
        if not cur.fetchone():
            cur.execute("""
                CREATE TABLE IF NOT EXISTS session_context (
                    session_id TEXT PRIMARY KEY,
                    summary TEXT DEFAULT '',
                    topic_chain TEXT DEFAULT '',
                    last_entities TEXT DEFAULT '',
                    rounds INTEGER DEFAULT 0,
                    updated_at REAL
                )
            """)
        self.db.conn.commit()

    def update_session_meta(self, session_id: str, entities: list,
                            topic: str = ""):
        """★ v3.9 F13: 每轮更新会话元数据 — 最近实体 + 话题链 + 轮数"""
        cur = self.db.conn.cursor()
        cur.execute("SELECT last_entities, topic_chain, rounds FROM session_context "
                    "WHERE session_id=?", (session_id,))
        row = cur.fetchone()
        rounds = (row[2] if row else 0) + 1
        # 最近实体: 新实体在前, 去重, 最多 6 个
        ents = [e for e in entities if e]
        if row and row[0]:
            for e in json.loads(row[0]):
                if e not in ents and len(ents) < 6:
                    ents.append(e)
        ents = ents[:6]
        # 话题链: 追加当前话题 (去重连续), 最多 8 个
        chain = []
        if row and row[1]:
            chain = json.loads(row[1])
        if topic and (not chain or chain[-1] != topic):
            chain.append(topic)
        chain = chain[-8:]
        cur.execute(
            "INSERT OR REPLACE INTO session_context "
            "(session_id, summary, topic_chain, last_entities, rounds, updated_at) "
            "VALUES (?,?,?,?,?,?)",
            (session_id, (row[0] if row else ""), json.dumps(chain, ensure_ascii=False),
             json.dumps(ents, ensure_ascii=False), rounds, time.time()))
        self.db.conn.commit()

    def roll_summary(self, session_id: str, every: int = 5) -> str:
        """★ v3.9 F13: 滚动会话摘要 — 每 every 轮浓缩最近 20 轮

        摘要 = 旧摘要(截断) + 新段落(第 X-Y 轮: 讨论实体/话题)
        长对话不丢前文: 8 轮窗口 + 滚动摘要 = 无限上下文感
        """
        cur = self.db.conn.cursor()
        cur.execute("SELECT summary, rounds FROM session_context WHERE session_id=?",
                    (session_id,))
        row = cur.fetchone()
        old_summary = (row[0] if row else "") or ""
        last_round = row[1] if row else 0
        # 只在轮数达到 every 的整数倍时才生成 (避免每轮都扫)
        if last_round < every or last_round % every != 0:
            return old_summary
        # 取最近 20 轮做要点提取
        recent = self.get_recent(session_id, n=20)
        texts = [r["content"] for r in recent]
        joined = " ".join(texts)
        # 高频词 (2-6 字中文) 作为讨论实体
        words = re.findall(r'[\u4e00-\u9fff]{2,6}', joined)
        freq = {}
        for w in words:
            if w in ("什么", "怎么", "为什么", "哪里", "可以", "我们", "这个", "那个", "就是", "不是", "一个", "一下", "没有", "知道", "觉得"):
                continue
            freq[w] = freq.get(w, 0) + 1
        top = [w for w, _ in sorted(freq.items(), key=lambda x: -x[1])[:6]]
        # 话题链
        topics = [r["topic"] for r in recent if r.get("topic")]
        tchain = "→".join(dict.fromkeys(topics)) if topics else ""
        seg = f"第{last_round - min(19, last_round)}-{last_round}轮: 围绕{'、'.join(top) if top else '一般话题'}讨论" \
              + (f"，话题[{tchain}]" if tchain else "")
        new_summary = (old_summary + " | " + seg) if old_summary else seg
        new_summary = new_summary[-800:]  # 截断, 防止无限膨胀
        cur.execute("UPDATE session_context SET summary=? WHERE session_id=?",
                    (new_summary, session_id))
        self.db.conn.commit()
        return new_summary

    def add(self, session_id: str, role: str, content: str, topic: str = ""):
        self.db.conn.execute(
            "INSERT INTO conversation_log (session_id, role, content, topic, timestamp) VALUES (?,?,?,?,?)",
            (session_id, role, content, topic, time.time())
        )
        self.db.conn.commit()

    def get_recent(self, session_id: str, n: int = None) -> list[dict]:
        """最近 N 轮对话"""
        n = n or self.max_recent
        cur = self.db.conn.cursor()
        cur.execute(
            "SELECT role, content, topic FROM conversation_log WHERE session_id=? ORDER BY id DESC LIMIT ?",
            (session_id, n)
        )
        return [{"role": r[0], "content": r[1], "topic": r[2]} for r in reversed(cur.fetchall())]

    def get_by_topic(self, topic: str, limit: int = 10) -> list[dict]:
        """按话题检索——类似 RAG"""
        cur = self.db.conn.cursor()
        cur.execute(
            "SELECT role, content, topic, timestamp FROM conversation_log "
            "WHERE topic LIKE ? OR content LIKE ? ORDER BY timestamp DESC LIMIT ?",
            (f"%{topic}%", f"%{topic}%", limit)
        )
        return [{"role": r[0], "content": r[1], "topic": r[2], "time": r[3]} for r in cur.fetchall()]

    def get_related_facts(self, text: str) -> list[str]:
        """从对话历史中找与当前输入相关的事实陈述"""
        keywords = re.findall(r'[\u4e00-\u9fff\w]{2,}', text)
        results = set()
        for kw in keywords[:5]:
            rows = self.get_by_topic(kw, limit=3)
            for row in rows:
                results.add(row["content"][:100])
        return list(results)[:5]

    def get_context_string(self, session_id: str, text: str, max_tokens: int = 500) -> str:
        """
        生成上下文字符串, 用于注入到 _process 的决策中。

        类似 LLM 把完整对话注入 prompt。
        ★ v3.9 F13: 先注入滚动摘要 (长对话前文) + 最近实体 (指代消解)
        """
        parts = []
        # ── F13: 会话滚动摘要 (前文不丢) ──
        cur = self.db.conn.cursor()
        cur.execute("SELECT summary, last_entities, topic_chain FROM session_context "
                    "WHERE session_id=?", (session_id,))
        srow = cur.fetchone()
        if srow and srow[0]:
            parts.append(f"--- Session summary: {srow[0][:300]}")
        if srow and srow[1]:
            ents = json.loads(srow[1])
            if ents:
                parts.append(f"--- Recent entities: {'、'.join(ents)}")
        if srow and srow[2]:
            chain = json.loads(srow[2])
            if chain:
                parts.append(f"--- Topic chain: {' → '.join(chain[-5:])}")

        recent = self.get_recent(session_id, n=8)
        for r in recent:
            parts.append(f"[{r['role']}]: {r['content'][:80]}")
        
        # 相关话题
        related = self.get_related_facts(text)
        if related:
            parts.append("--- Related context ---")
            for f in related[:3]:
                parts.append(f"  • {f}")

        return "\n".join(parts)
