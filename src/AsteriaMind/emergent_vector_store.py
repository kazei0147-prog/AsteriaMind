"""
EmergentVectorStore — 反馈驱动的向量认知存储 (AsteriaMind v3.2)

不是符号标签 (IS_A / CAN)。
是原始交互痕迹 → 向量化 → 相似检索 → 反馈预测。

学习阶段:
  用户说 "猫是哺乳动物" → 存 (subj, pred, obj, pattern, result)
  向量化整个模式 → 存入 SQLite

使用阶段:
  用户问 "海豚是哺乳动物吗"
  → 向量化
  → 检索最相似的历史交互
  → 如果相似历史都 ✅ → 高置信回答
  → 如果有 ❌ → 低置信反问

认知单元 = 交互模式在向量空间中的聚类。
没有标签。没有 IS_A。只有"这个模式以前成功过吗？"
"""
import json
import time
import math
import sqlite3
from typing import Optional


# ═══════════════════════════════════════
#  向量工具
# ═══════════════════════════════════════

def _simple_hash_vector(texts: list[str], dim: int = 64) -> list[float]:
    """
    极简向量化: 基于字符 n-gram 哈希。

    不需要嵌入模型——用统计特征就够了。
    目标不是语义完美，是能聚类相似模式。
    """
    vec = [0.0] * dim
    total = 0
    for text in texts:
        if text is None:
            text = ""  # 防止 len(None) 崩溃
        # n-grams: 2-gram + 3-gram
        for n in (2, 3):
            for i in range(len(text) - n + 1):
                h = hash(text[i:i+n]) % dim
                vec[h] += 1.0
                total += 1
    if total > 0:
        vec = [v / max(vec) for v in vec]  # normalize
    return vec


def cosine_similarity(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def vector_to_bytes(vec: list[float]) -> bytes:
    import struct
    return struct.pack(f'{len(vec)}f', *vec)


def bytes_to_vector(data: bytes) -> list[float]:
    import struct
    n = len(data) // 4
    return list(struct.unpack(f'{n}f', data))


# ═══════════════════════════════════════
#  EmergentVectorStore
# ═══════════════════════════════════════

class EmergentVectorStore:
    """
    反馈驱动的向量存储。

    每一条记录不是三元组——是完整的交互模式 + 反馈结果。
    """

    def __init__(self, db_path: str = "asteriamind.db"):
        self.conn = sqlite3.connect(db_path)
        self.conn.execute("PRAGMA journal_mode=WAL")
        self._ensure_table()

    def _ensure_table(self):
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS cognitive_traces (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                subj TEXT NOT NULL,
                pred TEXT NOT NULL,
                obj TEXT NOT NULL,
                pattern TEXT NOT NULL,
                feedback TEXT NOT NULL,
                vector BLOB NOT NULL,
                timestamp REAL,
                session_id TEXT DEFAULT ''
            );
            CREATE INDEX IF NOT EXISTS idx_ct_pattern ON cognitive_traces(pattern);
        """)
        self.conn.commit()

    def store(self, subj: str, pred: str, obj: str,
              feedback: str = "confirmed") -> int:
        """
        存入一条交互认知痕迹。

        subj, pred, obj: 原始三元组
        pattern: 抽象模式标识 (从词性推断)
        feedback: confirmed / corrected / unknown
        """
        subj = subj or ""
        pred = pred or ""
        obj = obj or ""
        pattern = f"{subj[:8]}::{pred}::{obj[:8]}"
        vec = _simple_hash_vector([subj, pred, obj, pattern, feedback])

        cur = self.conn.execute(
            "INSERT INTO cognitive_traces (subj, pred, obj, pattern, feedback, vector, timestamp) "
            "VALUES (?,?,?,?,?,?,?)",
            (subj, pred, obj, pattern, feedback, vector_to_bytes(vec), time.time())
        )
        self.conn.commit()
        return cur.lastrowid

    def query_similar(self, text: str, subj: str = "", pred: str = "",
                      obj: str = "", top_k: int = 5) -> list[dict]:
        """
        向量检索: 找到与当前输入最相似的认知痕迹。

        返回最近的 top_k 条，附带每条的历史反馈。
        """
        query_vec = _simple_hash_vector([text, subj, pred, obj])
        results = []

        for row in self.conn.execute(
            "SELECT id, subj, pred, obj, pattern, feedback, vector FROM cognitive_traces"
        ):
            stored_vec = bytes_to_vector(row[6])
            sim = cosine_similarity(query_vec, stored_vec)
            if sim > 0.3:
                results.append({
                    "id": row[0], "subj": row[1], "pred": row[2],
                    "obj": row[3], "pattern": row[4], "feedback": row[5],
                    "similarity": sim
                })

        results.sort(key=lambda r: r["similarity"], reverse=True)
        return results[:top_k]

    def predict_feedback(self, text: str, subj: str = "", pred: str = "",
                         obj: str = "") -> tuple[str, float, list[dict]]:
        """
        预测用户对新输入的反馈——认知单元的核心功能。

        返回: (predicted_feedback, confidence, evidence)
        """
        similar = self.query_similar(text, subj, pred, obj, top_k=10)
        if not similar:
            return ("unknown", 0.0, [])

        # 统计相似痕迹的反馈分布
        feedback_counts = {"confirmed": 0, "corrected": 0, "unknown": 0}
        for r in similar:
            fb = r["feedback"]
            if fb in feedback_counts:
                feedback_counts[fb] += 1

        total = sum(feedback_counts.values())
        if total == 0:
            return ("unknown", 0.0, similar)

        # 加权平均相似度
        confirmed_weight = sum(r["similarity"] for r in similar if r["feedback"] == "confirmed")
        corrected_weight = sum(r["similarity"] for r in similar if r["feedback"] == "corrected")

        if confirmed_weight > corrected_weight * 1.5:
            return ("confirmed", confirmed_weight / total, similar)
        elif corrected_weight > confirmed_weight * 1.5:
            return ("corrected", corrected_weight / total, similar)
        else:
            return ("unknown", 0.5, similar)

    def get_recent_traces(self, limit: int = 20) -> list[dict]:
        """获取最近的认知痕迹"""
        rows = self.conn.execute(
            "SELECT id, subj, pred, obj, feedback, timestamp FROM cognitive_traces "
            "ORDER BY id DESC LIMIT ?", (limit,)
        )
        return [{"id": r[0], "subj": r[1], "pred": r[2],
                 "obj": r[3], "feedback": r[4], "time": r[5]} for r in rows]

    def count(self) -> int:
        row = self.conn.execute("SELECT COUNT(*) FROM cognitive_traces").fetchone()
        return row[0] if row else 0


# ═══════════════════════════════════════
#  与 CognitiveInterface 的集成
# ═══════════════════════════════════════

def cognitive_query(store: EmergentVectorStore, text: str,
                    subj: str, pred: str, obj: str) -> dict:
    """
    认知查询——用向量存储做推断，替代简单的 KG 查找。

    学习阶段:
      AM 收到 "猫是哺乳动物" 且用户确认 → store("猫","IS_A","哺乳动物","confirmed")
      AM 收到 "猫是鱼" 且用户纠正 → store("猫","IS_A","鱼","corrected")

    使用阶段:
      用户问 "海豚是哺乳动物吗"
      → cognitive_query → 检索相似 → 预测"confirmed" → 回答"对"
    """
    trace = store.predict_feedback(text, subj, pred, obj)
    predicted_fb, confidence, evidence = trace

    return {
        "predicted": predicted_fb,
        "confidence": confidence,
        "evidence_count": len(evidence),
        "top_evidence": evidence[:3],
    }
