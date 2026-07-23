"""
EmergentVectorStore — 统一星图 (AsteriaMind v3.2 v2)

认知痕迹 + 语言痕迹共存于同一向量空间。
检索时同时返回认知推断 + 语言表达范式。
"""
import json, time, math, sqlite3, struct
from typing import Optional


def _simple_hash_vector(texts: list, dim: int = 64) -> list[float]:
    vec = [0.0] * dim
    total = 0
    for text in texts:
        if text is None: text = ""
        for n in (2, 3):
            for i in range(len(text) - n + 1):
                h = hash(text[i:i+n]) % dim
                vec[h] += 1.0
                total += 1
    if total > 0:
        mx = max(vec) or 1
        vec = [v / mx for v in vec]
    return vec


def cosine_similarity(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    return dot / (na * nb) if na * nb > 0 else 0.0


def vector_to_bytes(vec: list[float]) -> bytes:
    return struct.pack(f'{len(vec)}f', *vec)


def bytes_to_vector(data: bytes) -> list[float]:
    n = len(data) // 4
    return list(struct.unpack(f'{n}f', data))


class EmergentVectorStore:
    """统一星图——认知 + 语言同空间"""

    def __init__(self, db_path: str = "asteriamind.db"):
        self.conn = sqlite3.connect(db_path)
        self.conn.execute("PRAGMA journal_mode=WAL")
        self._ensure_table()

    def _ensure_table(self):
        c = self.conn.cursor()
        c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='language_traces'")
        if not c.fetchone():
            c.executescript("""
                CREATE TABLE IF NOT EXISTS cognitive_traces (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    subj TEXT NOT NULL, pred TEXT NOT NULL, obj TEXT NOT NULL,
                    pattern TEXT NOT NULL, feedback TEXT NOT NULL,
                    vector BLOB NOT NULL, timestamp REAL
                );
                CREATE TABLE IF NOT EXISTS language_traces (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    sentence TEXT NOT NULL,
                    subj TEXT NOT NULL, pred TEXT NOT NULL, obj TEXT NOT NULL,
                    cognitive_id INTEGER, vector BLOB NOT NULL,
                    pattern_type TEXT DEFAULT '', timestamp REAL
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
        subj, pred, obj = subj or "", pred or "", obj or ""
        pattern = f"{subj[:8]}::{pred}::{obj[:8]}"
        vec = _simple_hash_vector([subj, pred, obj, pattern, feedback])
        cur = self.conn.execute(
            "INSERT INTO cognitive_traces(subj,pred,obj,pattern,feedback,vector,timestamp) VALUES(?,?,?,?,?,?,?)",
            (subj, pred, obj, pattern, feedback, vector_to_bytes(vec), time.time()))
        cog_id = cur.lastrowid
        if text:
            lt = self._language_pattern(text)
            lvec = _simple_hash_vector([text, lt, subj, pred, obj])
            self.conn.execute(
                "INSERT INTO language_traces(sentence,subj,pred,obj,cognitive_id,vector,pattern_type,timestamp) VALUES(?,?,?,?,?,?,?,?)",
                (text, subj, pred, obj, cog_id, vector_to_bytes(lvec), lt, time.time()))
        self.conn.commit()
        return cog_id

    def predict_feedback(self, text: str, subj: str = "", pred: str = "",
                         obj: str = "") -> tuple[str, float, list]:
        qv = _simple_hash_vector([text, subj or "", pred or "", obj or ""])
        similar = []
        for r in self.conn.execute("SELECT id,subj,pred,obj,feedback,vector FROM cognitive_traces"):
            sim = cosine_similarity(qv, bytes_to_vector(r[5]))
            if sim > 0.3:
                similar.append({"id":r[0],"subj":r[1],"pred":r[2],"obj":r[3],"feedback":r[4],"similarity":sim})
        similar.sort(key=lambda x: x["similarity"], reverse=True)
        similar = similar[:10]
        if not similar:
            return ("unknown", 0.0, [])
        fc = {"confirmed": 0, "corrected": 0}
        for s in similar:
            fc[s["feedback"]] = fc.get(s["feedback"], 0) + s["similarity"]
        if fc.get("confirmed", 0) > fc.get("corrected", 0) * 1.5:
            return ("confirmed", fc["confirmed"] / len(similar), similar)
        elif fc.get("corrected", 0) > fc.get("confirmed", 0) * 1.5:
            return ("corrected", fc["corrected"] / len(similar), similar)
        return ("unknown", 0.5, similar)

    def emergent_reply(self, text: str, subj: str, pred: str, obj: str) -> dict:
        """统一检索: 认知+语言 → 涌现回复"""
        pf, conf, ev = self.predict_feedback(text, subj, pred, obj)
        qv = _simple_hash_vector([text, subj or "", pred or "", obj or ""])
        lang = []
        for r in self.conn.execute("SELECT sentence,pattern_type,subj,obj,vector FROM language_traces"):
            sim = cosine_similarity(qv, bytes_to_vector(r[4]))
            if sim > 0.2:
                lang.append({"sentence":r[0],"pattern":r[1],"subj":r[2],"obj":r[3],"similarity":sim})
        lang.sort(key=lambda x: x["similarity"], reverse=True)
        lang = lang[:3]

        # 涌现: 语言范式 + 认知证据 → 回复
        reply = self._assemble(pf, conf, ev, lang)
        return {"predicted": pf, "confidence": conf, "evidence": ev, "language": lang, "reply": reply}

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

    def query_similar(self, text: str, subj: str = "", pred: str = "",
                      obj: str = "", top_k: int = 5) -> list:
        qv = _simple_hash_vector([text, subj or "", pred or "", obj or ""])
        res = []
        for r in self.conn.execute("SELECT id,subj,pred,obj,pattern,feedback,vector FROM cognitive_traces"):
            sim = cosine_similarity(qv, bytes_to_vector(r[6]))
            if sim > 0.3:
                res.append({"id":r[0],"subj":r[1],"pred":r[2],"obj":r[3],"pattern":r[4],"feedback":r[5],"similarity":sim})
        res.sort(key=lambda x: x["similarity"], reverse=True)
        return res[:top_k]

    def count(self) -> int:
        return self.conn.execute("SELECT COUNT(*) FROM cognitive_traces").fetchone()[0]
