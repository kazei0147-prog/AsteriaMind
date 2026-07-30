"""
VectorLayer — 显式知识的语义补充层 (AsteriaMind v3.1)

不替代符号查询, 而是补充:
  精确查询 → 索引 O(1)
  语义查询 → 向量相似度 (类比/模糊匹配/关联发现)

纯 Python 实现, 零外部依赖:
  - TF-IDF 风格文本向量化
  - 余弦相似度检索
  - 可替换为 FAISS + sentence-transformers (接口一致)
"""
import math
import time
from dataclasses import dataclass, field
from typing import List, Tuple, Optional
import re


@dataclass
class VectorizedRelation:
    """一条知识的向量表示"""
    relation_key: str
    vector: List[float]     # 嵌入向量
    subject: str
    predicate: str
    object: str
    confidence: float
    embedded_at: float = field(default_factory=time.time)


class TextEmbedder:
    """
    轻量级文本嵌入: TF-IDF 风格的词袋 + 哈希。

    不依赖 sentence-transformers, 但接口相同:
      embed(text) → List[float]
    未来换模型只需替换这个类。
    """

    def __init__(self, dim: int = 128):
        self.dim = dim
        self._vocab: dict[str, int] = {}     # token → hash bucket
        self._idf: dict[str, float] = {}     # token → IDF weight
        self._doc_count = 0

    def embed(self, text: str) -> List[float]:
        """将文本转为 dim 维向量"""
        tokens = self._tokenize(text)
        if not tokens:
            return [0.0] * self.dim

        vec = [0.0] * self.dim
        for tok in tokens:
            idx = self._hash_token(tok)
            tf = tokens.count(tok) / len(tokens)  # term frequency
            idf = self._idf.get(tok, 1.0)          # inverse doc frequency
            vec[idx] += tf * idf
        # L2 归一化
        norm = math.sqrt(sum(v * v for v in vec))
        if norm > 0:
            vec = [v / norm for v in vec]
        return vec

    def fit(self, texts: List[str]):
        """批量学习 IDF 权重"""
        self._doc_count += len(texts)
        for text in texts:
            seen = set()
            for tok in self._tokenize(text):
                if tok not in seen:
                    self._idf[tok] = self._idf.get(tok, 0) + 1
                    seen.add(tok)
        # 转换计数 → IDF
        for tok in self._idf:
            self._idf[tok] = math.log((self._doc_count + 1) / (self._idf[tok] + 1)) + 1

    def _tokenize(self, text: str) -> List[str]:
        """简单分词: 中文按字符+双字, 英文按单词"""
        tokens = []
        # 英文单词
        tokens.extend(re.findall(r'[a-zA-Z]+', text.lower()))
        # 中文单字 + 双字
        chinese = re.sub(r'[a-zA-Z0-9\s]+', '', text)
        for i, ch in enumerate(chinese):
            tokens.append(ch)
            if i + 1 < len(chinese):
                tokens.append(chinese[i:i+2])
        return tokens

    def _hash_token(self, token: str) -> int:
        """将 token 映射到 [0, dim)"""
        if token not in self._vocab:
            self._vocab[token] = hash(token) % self.dim
        return self._vocab[token]


class VectorLayer:
    """
    向量语义层: 精确查询的补充。

    用法:
      vl = VectorLayer(dim=128)
      vl.index_relation("咖啡--[CAUSES]-->清醒", "咖啡 导致 清醒 提神")
      results = vl.search("什么东西让人清醒?", top_k=5)
    """

    def __init__(self, dim: int = 128):
        self.dim = dim
        self.embedder = TextEmbedder(dim=dim)
        self.relations: List[VectorizedRelation] = []
        self._dirty = False  # 是否有新关系未更新 IDF

    def index_relation(self, key: str, text: str, subject: str = "",
                       predicate: str = "", object: str = "",
                       confidence: float = 0.5):
        """为一条知识创建向量索引"""
        vec = self.embedder.embed(text)
        self.relations.append(VectorizedRelation(
            relation_key=key, vector=vec,
            subject=subject, predicate=predicate, object=object,
            confidence=confidence,
        ))
        self._dirty = True

    def batch_index(self, relations: list):
        """批量索引——收集所有文本, 统一计算 IDF, 然后嵌入"""
        texts = []
        entries = []
        for r in relations:
            if hasattr(r, 'subject'):
                text = f"{r.subject} {r.predicate} {r.object}"
                entries.append((r.key(), r.subject, r.predicate, r.object, r.confidence, text))
            else:
                key, text = r
                entries.append((key, "", "", "", 0.5, text))
            texts.append(entries[-1][-1])

        # 批量学习 IDF
        self.embedder.fit(texts)

        # 批量嵌入
        for key, subj, pred, obj, conf, text in entries:
            vec = self.embedder.embed(text)
            self.relations.append(VectorizedRelation(
                relation_key=key, vector=vec,
                subject=subj, predicate=pred, object=obj, confidence=conf,
            ))
        self._dirty = False

    def search(self, query: str, top_k: int = 5,
               min_similarity: float = 0.1) -> List[Tuple[str, float, dict]]:
        """
        语义搜索: 找到与 query 最相似的 k 条知识。

        返回: [(relation_key, similarity, metadata), ...]
        """
        if self._dirty:
            self._rebuild_idf()

        query_vec = self.embedder.embed(query)
        scores = []
        for vr in self.relations:
            sim = self._cosine(query_vec, vr.vector)
            if sim >= min_similarity:
                scores.append((vr.relation_key, sim, {
                    "subject": vr.subject, "predicate": vr.predicate,
                    "object": vr.object, "confidence": vr.confidence,
                }))
        scores.sort(key=lambda x: -x[1])
        return scores[:top_k]

    def analogy(self, concept: str, top_k: int = 5) -> List[Tuple[str, float]]:
        """类比推理: 找到与 concept 在向量空间中最接近的知识"""
        return [(key, sim) for key, sim, _ in self.search(concept, top_k)]

    def find_associations(self, min_similarity: float = 0.3) -> List[Tuple[str, str, float]]:
        """
        关联发现: 找到向量空间中彼此高度相似但没有直接关系连接的知识对。
        这是语义层的"你可能不知道这两者相关"的推荐。
        """
        pairs = []
        for i, a in enumerate(self.relations):
            for j, b in enumerate(self.relations):
                if j <= i:
                    continue
                sim = self._cosine(a.vector, b.vector)
                if sim >= min_similarity:
                    pairs.append((a.relation_key, b.relation_key, sim))
        pairs.sort(key=lambda x: -x[2])
        return pairs[:20]

    def evolution_trace(self, key: str) -> List[dict]:
        """知识演化追踪: 查找同一 key 的多个版本 (需要时间戳支持)"""
        matches = [vr for vr in self.relations if vr.relation_key == key]
        if len(matches) < 2:
            return []
        traces = []
        for prev, curr in zip(matches[:-1], matches[1:]):
            drift = 1 - self._cosine(prev.vector, curr.vector)
            traces.append({
                "from_time": prev.embedded_at,
                "to_time": curr.embedded_at,
                "vector_drift": drift,
                "confidence_change": curr.confidence - prev.confidence,
            })
        return traces

    def _cosine(self, a: List[float], b: List[float]) -> float:
        dot = sum(x * y for x, y in zip(a, b))
        na = math.sqrt(sum(x * x for x in a))
        nb = math.sqrt(sum(x * x for x in b))
        if na == 0 or nb == 0:
            return 0.0
        return dot / (na * nb)

    def _rebuild_idf(self):
        """当有脏数据时重建 IDF"""
        texts = [f"{vr.subject} {vr.predicate} {vr.object}" for vr in self.relations]
        self.embedder.fit(texts)
        # 重建所有向量
        for vr in self.relations:
            text = f"{vr.subject} {vr.predicate} {vr.object}"
            vr.vector = self.embedder.embed(text)
        self._dirty = False
