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
        # ★ v3.9 F18 (瓶颈二): 句间衔接统计表 — 为 F13 会话上下文铺语言层基础
        #   统计"上一句特征 → 下一句开头词"的轮次对, 让多轮连贯有据可依
        self.conn.execute(
            "CREATE TABLE IF NOT EXISTS dialogue_transitions("
            "prev_intent TEXT, prev_negation INTEGER DEFAULT 0, "
            "prev_topic TEXT, next_opener TEXT, count INTEGER DEFAULT 1, "
            "last_update REAL, "
            "PRIMARY KEY(prev_intent, prev_negation, prev_topic, next_opener))")
        self.conn.commit()

    # ── ★ v3.9 F18 (瓶颈二): 句间衔接特征提取 ──
    _QUESTION_MARK = re.compile(r'[吗么呢？?]$|[是不是|会不会|能不能|有没有|为什么|如何]')
    _NEGATION_WORDS = ('不', '没', '别', '错', '否', '非')
    _OPENER_STOP = ('嗯', '啊', '哦', '呃', '诶', '哎', '哈')
    _TOPIC_STOP = ('什么', '怎么', '为什么', '哪个', '哪些', '哪里', '如何',
                   '这', '那', '你', '我', '他', '她', '它', '的', '了', '吗',
                   '呢', '是', '会', '能', '有', '吗', '的', '们')

    @classmethod
    def _prev_intent(cls, text: str) -> str:
        """上一句的语用类型: question / negate / statement"""
        t = (text or "").strip()
        if cls._NEGATION_WORDS and any(
                w in t for w in ("不对", "错了", "不是", "不对哦", "说错了")):
            return "negate"
        if cls._QUESTION_MARK.search(t) or t.endswith(('吗', '呢', '么')):
            return "question"
        return "statement"

    @classmethod
    def _prev_topic(cls, text: str) -> str:
        """上一句的话题词: 去掉虚词/问词后取前 2-4 字"""
        t = (text or "").strip()
        for w in cls._TOPIC_STOP:
            t = t.replace(w, "")
        t = re.sub(r'[^\u4e00-\u9fff]', '', t)
        return t[:3] if t else ""

    @classmethod
    def _next_opener(cls, text: str) -> str:
        """下一句开头词: 去语气词后取前 2 字"""
        t = (text or "").strip()
        for w in cls._OPENER_STOP:
            if t.startswith(w):
                t = t[len(w):]
                break
        return t[:2] if t else ""

    def learn_transition(self, prev_text: str, next_text: str) -> bool:
        """★ v3.9 F18: 记录一个轮次对 (上一句 → 下一句的衔接特征)
        数据源: conversation_log 真实轮次 (批量回放) + web 实时回流
        """
        if not prev_text or not next_text:
            return False
        intent = self._prev_intent(prev_text)
        neg = 1 if any(w in prev_text for w in
                       ("不", "没", "别", "错")) else 0
        topic = self._prev_topic(prev_text)
        opener = self._next_opener(next_text)
        if not opener:
            return False
        try:
            # UPSERT: 新行 count=1, 已存在 count+1 (避免 INSERT OR IGNORE + UPDATE 双重计数)
            self.conn.execute(
                "INSERT INTO dialogue_transitions"
                "(prev_intent, prev_negation, prev_topic, next_opener, count, last_update) "
                "VALUES (?,?,?,?,1,?) "
                "ON CONFLICT(prev_intent, prev_negation, prev_topic, next_opener) "
                "DO UPDATE SET count=count+1, last_update=excluded.last_update",
                (intent, neg, topic, opener, time.time()))
            self.conn.commit()
            return True
        except Exception:
            return False

    def transition_stats(self) -> dict:
        """句间衔接统计摘要 (供观察: 语言层多轮衔接基础是否在长)"""
        try:
            total = self.conn.execute(
                "SELECT COALESCE(SUM(count),0) FROM dialogue_transitions").fetchone()[0]
            patterns = self.conn.execute(
                "SELECT COUNT(*) FROM dialogue_transitions").fetchone()[0]
            top = self.conn.execute(
                "SELECT prev_intent, next_opener, SUM(count) FROM dialogue_transitions "
                "GROUP BY prev_intent, next_opener ORDER BY 3 DESC LIMIT 5").fetchall()
            return {"total_transitions": total, "patterns": patterns,
                    "top": [{"prev": r[0], "opener": r[1], "count": r[2]} for r in top]}
        except Exception:
            return {"total_transitions": 0, "patterns": 0, "top": []}

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
        prev_user_text = ""
        for cid, content in rows:
            if cid in done:
                continue
            ok = self.ingest(content)
            if ok:
                n_new += 1
            else:
                n_skip += 1
            # ★ v3.9 F18 (瓶颈二): 回放时顺带学轮次对 (时间倒序, 相邻两条即一对)
            if prev_user_text:
                self.learn_transition(content, prev_user_text)
            prev_user_text = content
            self.conn.execute(
                "INSERT OR IGNORE INTO replayed_conv VALUES (?)", (cid,))
        self.conn.commit()
        return {"replayed": n_new, "skipped": n_skip, "scanned": len(rows)}
