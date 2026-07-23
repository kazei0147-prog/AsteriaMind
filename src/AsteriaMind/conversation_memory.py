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
        self.db.conn.commit()

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
        """
        parts = []
        recent = self.get_recent(session_id, n=8)
        for r in recent:
            parts.append(f"[{r['role']}]: {r['content'][:80]}")
        
        # 相关话题
        related = self.get_related_facts(text)
        if related:
            parts.append("--- Related context ---")
            for f in related[:3]:
                parts.append(f"  • {f}")

        # 当前话题链
        topics = [r['topic'] for r in recent if r['topic']]
        if topics:
            parts.append(f"--- Topic chain: {' → '.join(topics[-5:])}")

        return "\n".join(parts)
