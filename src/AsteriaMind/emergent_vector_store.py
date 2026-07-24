"""
EmergentVectorStore — 统一星图 v3 (共现引擎 + 语言涌现)

v3: 统计共近代替代字符哈希。
认知痕迹 → 自动构建共现矩阵 → 稀疏向量 → 相似检索。
认知 + 语言痕迹共存于同一空间，同时检索。
"""
import time, math, sqlite3, struct
from typing import Optional


# ═══════════════════════════════════════
#  共现向量引擎
# ═══════════════════════════════════════

def _build_cooccur_from_traces(conn: sqlite3.Connection):
    """从 cognitive_traces 构建/增量更新共现表"""
    cur = conn.cursor()
    cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='co_occurrence'")
    if cur.fetchone():
        return  # 已存在
    cur.execute("""
        CREATE TABLE co_occurrence (
            entity_a TEXT NOT NULL,
            entity_b TEXT NOT NULL,
            count INTEGER DEFAULT 1,
            PRIMARY KEY (entity_a, entity_b)
        )
    """)
    for row in cur.execute("SELECT subj, pred, obj FROM cognitive_traces"):
        subj, pred, obj = (row[0] or "").strip(), (row[1] or "").strip(), (row[2] or "").strip()
        _incr_cooccur(cur, subj, pred)
        _incr_cooccur(cur, subj, obj)
        _incr_cooccur(cur, pred, obj)
    conn.commit()


def _incr_cooccur(cur, a: str, b: str):
    if not a or not b or a == b:
        return
    if a > b:
        a, b = b, a
    cur.execute(
        "INSERT INTO co_occurrence(entity_a,entity_b,count) VALUES(?,?,1) "
        "ON CONFLICT(entity_a,entity_b) DO UPDATE SET count=count+1",
        (a, b))


def _entity_vector(conn, entity: str) -> dict[str, int]:
    """单实体共现向量"""
    vec = {}
    for row in conn.execute(
        "SELECT entity_b, count FROM co_occurrence WHERE entity_a=? "
        "UNION ALL SELECT entity_a, count FROM co_occurrence WHERE entity_b=?",
        (entity, entity)):
        vec[row[0]] = row[1]
    return vec


def _query_vector(conn, subj: str, obj: str, pred: str = "") -> dict[str, int]:
    """组合查询向量 (多实体共现合并)"""
    vec: dict[str, int] = {}
    for e in (subj, obj, pred):
        if e:
            for k, v in _entity_vector(conn, e).items():
                vec[k] = vec.get(k, 0) + v
    return vec


def _sparse_cosine(v1: dict[str, int], v2: dict[str, int]) -> float:
    """稀疏向量余弦相似度"""
    if not v1 or not v2:
        return 0.0
    dot = sum(v1.get(k, 0) * v2.get(k, 0) for k in set(v1) & set(v2))
    n1 = math.sqrt(sum(v * v for v in v1.values()))
    n2 = math.sqrt(sum(v * v for v in v2.values()))
    return dot / (n1 * n2) if n1 * n2 > 0 else 0.0


# ═══════════════════════════════════════
#  EmergentVectorStore
# ═══════════════════════════════════════

class EmergentVectorStore:
    """统一星图——共现向量 + 语言涌现"""

    def __init__(self, db_path: str = "asteriamind.db"):
        self.conn = sqlite3.connect(db_path)
        self.conn.execute("PRAGMA journal_mode=WAL")
        self._ensure_table()
        _build_cooccur_from_traces(self.conn)

    def _ensure_table(self):
        c = self.conn.cursor()
        c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='language_traces'")
        if not c.fetchone():
            c.executescript("""
                CREATE TABLE IF NOT EXISTS cognitive_traces (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    subj TEXT NOT NULL, pred TEXT NOT NULL, obj TEXT NOT NULL,
                    pattern TEXT NOT NULL, feedback TEXT NOT NULL,
                    timestamp REAL
                );
                CREATE TABLE IF NOT EXISTS language_traces (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    sentence TEXT NOT NULL,
                    subj TEXT NOT NULL, pred TEXT NOT NULL, obj TEXT NOT NULL,
                    cognitive_id INTEGER, pattern_type TEXT DEFAULT '', timestamp REAL
                );
                CREATE INDEX IF NOT EXISTS idx_ct_pattern ON cognitive_traces(pattern);
                CREATE INDEX IF NOT EXISTS idx_lt_pattern ON language_traces(pattern_type);
            """)
        self.conn.commit()

    @staticmethod
    def _language_pattern(sentence: str) -> str:
        if '属于' in sentence: return 'X属于Y'
        if '会' in sentence and '吗' in sentence: return 'X会Y吗'
        if '是' in sentence and '吗' in sentence: return 'X是Y吗'
        if '会' in sentence: return 'X会Y'
        if '绕' in sentence: return 'X绕Y'
        if '是' in sentence: return 'X是Y'
        if '吗' in sentence: return '问句'
        return '陈述'

    def store(self, subj: str, pred: str, obj: str,
              feedback: str = "confirmed", text: str = "") -> int:
        """存入认知痕迹 + 语言痕迹 + 更新共现"""
        subj = (subj or "").strip()
        pred = (pred or "").strip()
        obj = (obj or "").strip()
        pattern = f"{subj[:8]}::{pred}::{obj[:8]}"
        cur = self.conn.execute(
            "INSERT INTO cognitive_traces(subj,pred,obj,pattern,feedback,timestamp) "
            "VALUES(?,?,?,?,?,?)",
            (subj, pred, obj, pattern, feedback, time.time()))
        cog_id = cur.lastrowid
        if text:
            lt = self._language_pattern(text)
            self.conn.execute(
                "INSERT INTO language_traces(sentence,subj,pred,obj,cognitive_id,pattern_type,timestamp) "
                "VALUES(?,?,?,?,?,?,?)",
                (text, subj, pred, obj, cog_id, lt, time.time()))
        # 更新共现
        _incr_cooccur(self.conn.cursor(), subj, pred)
        _incr_cooccur(self.conn.cursor(), subj, obj)
        _incr_cooccur(self.conn.cursor(), pred, obj)
        self.conn.commit()
        return cog_id

    def query_similar(self, text: str = "", subj: str = "", pred: str = "",
                      obj: str = "", top_k: int = 5) -> list:
        """共现向量检索"""
        qv = _query_vector(self.conn, subj, obj, pred)
        res = []
        for row in self.conn.execute(
            "SELECT id,subj,pred,obj,pattern,feedback FROM cognitive_traces"):
            tv = _query_vector(self.conn, row[1], row[3], row[2])
            sim = _sparse_cosine(qv, tv)
            if sim > 0.0:
                res.append({"id": row[0], "subj": row[1], "pred": row[2],
                            "obj": row[3], "pattern": row[4], "feedback": row[5],
                            "similarity": sim})
        res.sort(key=lambda x: x["similarity"], reverse=True)
        return res[:top_k]

    def predict_feedback(self, text: str = "", subj: str = "", pred: str = "",
                         obj: str = "") -> tuple[str, float, list]:
        """共现预测反馈"""
        qv = _query_vector(self.conn, subj, obj, pred)
        similar = []
        for row in self.conn.execute(
            "SELECT id,subj,pred,obj,pattern,feedback FROM cognitive_traces"):
            tv = _query_vector(self.conn, row[1], row[3], row[2])
            sim = _sparse_cosine(qv, tv)
            if sim > 0.0:
                similar.append({"id": row[0], "subj": row[1], "pred": row[2],
                                "obj": row[3], "pattern": row[4], "feedback": row[5],
                                "similarity": sim})
        similar.sort(key=lambda x: x["similarity"], reverse=True)
        similar = similar[:10]
        if not similar:
            return ("unknown", 0.0, [])
        fc = {"confirmed": 0.0, "corrected": 0.0}
        for s in similar:
            fc[s["feedback"]] = fc.get(s["feedback"], 0.0) + s["similarity"]
        total = sum(fc.values()) or 1
        if fc.get("confirmed", 0) > fc.get("corrected", 0) * 1.5:
            return ("confirmed", fc["confirmed"] / total, similar)
        if fc.get("corrected", 0) > fc.get("confirmed", 0) * 1.5:
            return ("corrected", fc["corrected"] / total, similar)
        return ("unknown", 0.5, similar)

    def emergent_reply(self, text: str, subj: str, pred: str, obj: str) -> dict:
        """共现 + 语言统一检索 → 涌现回复"""
        pf, conf, ev = self.predict_feedback(text, subj, pred, obj)
        qv = _query_vector(self.conn, subj, obj, pred)
        lang = []
        for row in self.conn.execute(
            "SELECT sentence,pattern_type,subj,obj FROM language_traces"):
            tv = _query_vector(self.conn, row[2], row[3], "")
            sim = _sparse_cosine(qv, tv)
            if sim > 0.0:
                lang.append({"sentence": row[0], "pattern": row[1],
                             "subj": row[2], "obj": row[3], "similarity": sim})
        lang.sort(key=lambda x: x["similarity"], reverse=True)
        lang = lang[:3]
        reply = self._assemble(pf, conf, ev, lang)
        return {"predicted": pf, "confidence": conf, "evidence": ev,
                "language": lang, "reply": reply}

    def _assemble(self, predicted: str, confidence: float,
                  evidence: list, language: list) -> str:
        if not evidence:
            return f"我还不太了解 (置信{confidence:.0%})。你能教我吗?"
        nearest = evidence[0]
        if predicted == "confirmed" and confidence > 0.3:
            return f"对——就像「{nearest['subj']} {nearest['pred']} {nearest['obj']}」一样。(置信{confidence:.0%})"
        if predicted == "corrected" and confidence > 0.3:
            return f"不对——「{nearest['subj']} {nearest['pred']} {nearest['obj']}」曾被纠正过。"
        return f"还不太确定 (置信{confidence:.0%})"

    def count(self) -> int:
        return self.conn.execute("SELECT COUNT(*) FROM cognitive_traces").fetchone()[0]
