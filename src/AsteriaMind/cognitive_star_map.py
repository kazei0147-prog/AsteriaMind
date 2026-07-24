"""
CognitiveStarMap — 统一星图 v3 (共现引擎 + 语言涌现)

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
    """从 cognitive_traces 构建/升级共现表"""
    cur = conn.cursor()
    cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='co_occurrence'")
    if cur.fetchone():
        # 检查是否需要升级 schema (old: count only, new: weight/confidence/evidence/last_update)
        cols = {r[1] for r in conn.execute("PRAGMA table_info(co_occurrence)")}
        if "confidence" not in cols:
            cur.execute("ALTER TABLE co_occurrence ADD COLUMN confidence REAL DEFAULT 1.0")
            cur.execute("ALTER TABLE co_occurrence ADD COLUMN evidence_count INTEGER DEFAULT 1")
            cur.execute("ALTER TABLE co_occurrence ADD COLUMN last_update REAL DEFAULT 0")
            # 从已有 count 初始化
            cur.execute("UPDATE co_occurrence SET evidence_count=count, confidence=1.0, last_update=0")
            conn.commit()
        return

    cur.execute("""
        CREATE TABLE co_occurrence (
            entity_a TEXT NOT NULL,
            entity_b TEXT NOT NULL,
            weight INTEGER DEFAULT 1,
            confidence REAL DEFAULT 1.0,
            evidence_count INTEGER DEFAULT 1,
            last_update REAL DEFAULT 0,
            PRIMARY KEY (entity_a, entity_b)
        )
    """)
    for row in cur.execute("SELECT subj, pred, obj, feedback FROM cognitive_traces"):
        subj, pred, obj = (row[0] or "").strip(), (row[1] or "").strip(), (row[2] or "").strip()
        fb = row[3] or "confirmed"
        _incr_cooccur(cur, subj, pred, fb, time.time())
        _incr_cooccur(cur, subj, obj, fb, time.time())
        _incr_cooccur(cur, pred, obj, fb, time.time())
    conn.commit()


DECAY_LAMBDA = 0.01  # 衰减系数: 越大遗忘越快


def _incr_cooccur(cur, a: str, b: str, feedback: str = "confirmed", ts: float = 0):
    """更新边权: weight+1, confidence 根据反馈调整, evidence_count+1"""
    if not a or not b or a == b:
        return
    if a > b:
        a, b = b, a
    conf_boost = 1.0 if feedback == "confirmed" else (0.3 if feedback == "corrected" else 0.5)
    ts = ts or time.time()
    cur.execute(
        "INSERT INTO co_occurrence(entity_a,entity_b,weight,confidence,evidence_count,last_update) "
        "VALUES(?,?,1,?,1,?) "
        "ON CONFLICT(entity_a,entity_b) DO UPDATE SET "
        "weight=weight+1, "
        "confidence=(confidence*evidence_count+?)/(evidence_count+1), "
        "evidence_count=evidence_count+1, "
        "last_update=?",
        (a, b, conf_boost, ts, conf_boost, ts))


def _effective_weight(row) -> float:
    """动态边权: weight × confidence × time_decay"""
    weight = row[0] if isinstance(row, tuple) else row["weight"]
    conf = row[1] if isinstance(row, tuple) else row["confidence"]
    last_up = row[2] if isinstance(row, tuple) else row["last_update"]
    decay = math.exp(-DECAY_LAMBDA * (time.time() - (last_up or 0)) / 86400)  # 按天衰减
    return float(weight) * float(conf) * float(decay)


def _entity_vector(conn, entity: str) -> dict[str, float]:
    """单实体共现向量——用有效权重"""
    vec = {}
    now = time.time()
    decay_factor = math.exp(-DECAY_LAMBDA * now / 86400)
    for row in conn.execute(
        "SELECT entity_b, weight, confidence, last_update FROM co_occurrence WHERE entity_a=? "
        "UNION ALL SELECT entity_a, weight, confidence, last_update FROM co_occurrence WHERE entity_b=?",
        (entity, entity)):
        w = _effective_weight(row[1:])  # row[0] 是实体名, row[1:]= weight,confidence,last_update
        if w > 0.01:
            vec[row[0]] = w
    return vec


def _query_vector(conn, subj: str, obj: str, pred: str = "") -> dict[str, float]:
    """组合查询向量"""
    vec: dict[str, float] = {}
    for e in (subj, obj, pred):
        if e:
            for k, v in _entity_vector(conn, e).items():
                vec[k] = vec.get(k, 0.0) + v
    return vec


def _sparse_cosine(v1: dict[str, float], v2: dict[str, float]) -> float:
    """稀疏向量余弦相似度"""
    if not v1 or not v2:
        return 0.0
    dot = sum(v1.get(k, 0) * v2.get(k, 0) for k in set(v1) & set(v2))
    n1 = math.sqrt(sum(v * v for v in v1.values()))
    n2 = math.sqrt(sum(v * v for v in v2.values()))
    return dot / (n1 * n2) if n1 * n2 > 0 else 0.0


# ═══════════════════════════════════════
#  CognitiveStarMap
# ═══════════════════════════════════════

class CognitiveStarMap:
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

    def _cooccur_neighbors(self, entities: list[str], top_k: int = 20) -> set[str]:
        """
        低频准备: 从共现表快速捞出相关实体。

        "哺乳动物" → [猫, 狗, 海豚, 蝙蝠, ...]
        不在每次检索时扫全表，只激活局部子图。
        """
        neighbors = set(e for e in entities if e)
        cur = self.conn.cursor()
        for e in entities:
            if not e: continue
            for sql, col in (
                ("SELECT entity_b FROM co_occurrence WHERE entity_a=? "
                 "ORDER BY weight*confidence DESC LIMIT ?", 0),
                ("SELECT entity_a FROM co_occurrence WHERE entity_b=? "
                 "ORDER BY weight*confidence DESC LIMIT ?", 0),
            ):
                for row in cur.execute(sql, (e, top_k)):
                    if row[col] and row[col] != e:
                        neighbors.add(row[col])
        return neighbors

    def _indexed_scan(self, qv: dict, activated: set[str]) -> list:
        """
        高频局部激活: 只在相关实体的认知痕迹中计算相似度。

        WHERE subj IN (...) OR obj IN (...) → 子图扫描。
        """
        if not activated:
            return []
        placeholders = ",".join("?" * len(activated))
        params = list(activated) + list(activated)
        sql = (f"SELECT id,subj,pred,obj,pattern,feedback FROM cognitive_traces "
               f"WHERE subj IN ({placeholders}) OR obj IN ({placeholders})")
        res = []
        for row in self.conn.execute(sql, params):
            tv = _query_vector(self.conn, row[1], row[3], row[2])
            sim = _sparse_cosine(qv, tv)
            if sim > 0.0:
                res.append({"id": row[0], "subj": row[1], "pred": row[2],
                            "obj": row[3], "pattern": row[4], "feedback": row[5],
                            "similarity": sim})
        res.sort(key=lambda x: x["similarity"], reverse=True)
        return res

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
        # 更新共现边权
        ts = time.time()
        _incr_cooccur(self.conn.cursor(), subj, pred, feedback, ts)
        _incr_cooccur(self.conn.cursor(), subj, obj, feedback, ts)
        _incr_cooccur(self.conn.cursor(), pred, obj, feedback, ts)
        self.conn.commit()
        return cog_id

    def query_similar(self, text: str = "", subj: str = "", pred: str = "",
                      obj: str = "", top_k: int = 5) -> list:
        """共现索引检索 —— 低频准备 + 高频局部激活"""
        qv = _query_vector(self.conn, subj, obj, pred)
        activated = self._cooccur_neighbors([subj, obj, pred])
        return self._indexed_scan(qv, activated)[:top_k]

    def predict_feedback(self, text: str = "", subj: str = "", pred: str = "",
                         obj: str = "") -> tuple[str, float, list]:
        """共现索引预测 —— 只在激活子图中运算"""
        qv = _query_vector(self.conn, subj, obj, pred)
        activated = self._cooccur_neighbors([subj, obj, pred])
        similar = self._indexed_scan(qv, activated)[:10]
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
        activated = self._cooccur_neighbors([subj, obj, pred])
        lang = []
        placeholders = ",".join("?" * len(activated))
        sql = (f"SELECT sentence,pattern_type,subj,obj FROM language_traces "
               f"WHERE subj IN ({placeholders}) OR obj IN ({placeholders})")
        for row in self.conn.execute(sql, list(activated) + list(activated)):
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
