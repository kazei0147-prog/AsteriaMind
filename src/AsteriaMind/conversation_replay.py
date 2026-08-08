"""
ConversationReplay — 对话语料回流 (AsteriaMind v3.8)

关键洞察: 她自己的对话史是最好的语料
  用户的话 = 目标语言 (她该学的说话方式)
  对话句式 vs 散文句式: "企鹅会飞吗" 比 "企鹅虽然是鸟类" 干净得多
  语言能力 = 语料形状 → 喂对话 → 学会对话

只回流传 role='user' 的消息:
  - AM 自己的回复是当前水平, 回流会自我强化 (锁死坏句式)
  - 用户的话是目标, 是"老师"

过滤:
  - 长度 2-60 (太短没句式, 太长是粘贴)
  - 命令类前缀 (教我/查一下/算一下...) — 指令不是对话
  - emoji / 无中文 — 噪音

输出: language_traces (sentence_type='user_dialogue')
  → LanguageModel.mine() 自动吸收 → 骨架池长对话句式
"""

import sqlite3
import time
import re

_DB = "asteriamind.db"

# 命令类前缀 (指令句式 ≠ 对话句式)
_CMD_PREFIX = ('教我', '查一下', '查一查', '查下', '算一下', '算算', '搜一下',
               '搜索', '查找', '检索', 'learnw', 'readcn', 'answer', '以后我',
               '帮我', '讲一下', '介绍一下', '说说', '记一下', '记住')

# emoji 范围
_EMOJI_RE = re.compile(
    r'[\U0001F000-\U0001FAFF\u2600-\u27BF\u2190-\u21FF\u2B00-\u2BFF]')


class ConversationReplay:
    def __init__(self, db: str = _DB):
        self.conn = sqlite3.connect(db, timeout=10)
        self.conn.execute(
            "CREATE TABLE IF NOT EXISTS replayed_conv(id INTEGER PRIMARY KEY)")

    @staticmethod
    def is_teachable(text: str) -> bool:
        """这段用户话值得学吗? (对话句式, 不是指令/噪音)"""
        t = (text or "").strip()
        if len(t) < 2 or len(t) > 60:
            return False
        if t.startswith(_CMD_PREFIX):
            return False
        if _EMOJI_RE.search(t):
            return False
        if not any('\u4e00' <= c <= '\u9fff' for c in t):
            return False
        return True

    def ingest(self, text: str) -> bool:
        """单句实时回流 (web 每次用户消息调用)"""
        if not self.is_teachable(text):
            return False
        try:
            self.conn.execute(
                "INSERT INTO language_traces"
                "(sentence, subj, pred, obj, timestamp, sentence_type) "
                "VALUES (?, '', '', '', ?, 'user_dialogue')",
                (text.strip()[:200], time.time()))
            self.conn.commit()
            return True
        except Exception:
            return False

    def replay_history(self, limit: int = 600) -> dict:
        """批量回放 conversation_log 里的用户消息 (一次性, 历史补齐)"""
        done = {r[0] for r in
                self.conn.execute("SELECT id FROM replayed_conv").fetchall()}
        rows = self.conn.execute(
            "SELECT id, content FROM conversation_log "
            "WHERE role='user' ORDER BY id DESC LIMIT ?",
            (limit,)).fetchall()
        n_new = n_skip = 0
        for cid, content in rows:
            if cid in done:
                continue
            ok = self.ingest(content)
            if ok:
                n_new += 1
            else:
                n_skip += 1
            self.conn.execute(
                "INSERT OR IGNORE INTO replayed_conv VALUES (?)", (cid,))
        self.conn.commit()
        return {"replayed": n_new, "skipped": n_skip, "scanned": len(rows)}
