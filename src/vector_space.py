"""
vector_space.py — AM 的向量空间 (黑盒语义层)
=============================================
从语料训练 word2vec → 存 SQLite → 提供语义近邻查询

哲学:
  预输入给分类 (白盒): 地球 IS_A 行星   ← 种子包教的
  向量空间让她自己长分类 (黑盒): 从语料共现自动学
    '天王星 ≈ 海王星 ≈ 木星' 不用人教, 她能从向量距离自己猜

表: word_vectors(word TEXT PRIMARY KEY, vector BLOB, dim INT)
API: /api/vector?word=X → 语义近邻 top10
"""

import os
import re
import sqlite3
import sys
import time

import numpy as np

_CORPUS_DIR = "D:/AM/corpus"
_DB = "asteriamind.db"
_DIM = 128


# ── 1. 分词 (jieba) ──
def tokenize(text: str) -> list:
    """jieba 分词: 保留中文词 + 英文词, 过滤单字/纯数字"""
    import jieba
    text = re.sub(r"[^\u4e00-\u9fff\w]", " ", text)
    words = []
    for w in jieba.cut(text):
        w = w.strip()
        if len(w) >= 2 and not re.match(r"^\d+$", w):
            words.append(w)
    return words


# ── 2. 训练 ──
def train(corpus_dir: str = _CORPUS_DIR, dim: int = _DIM,
          min_count: int = 2, epochs: int = 5):
    """扫描语料 → 分句分词 → 训练 word2vec (CBOW)"""
    from gensim.models import Word2Vec

    sentences = []
    for f in os.listdir(corpus_dir):
        path = os.path.join(corpus_dir, f)
        if not (os.path.isfile(path) and f.endswith(".txt")):
            continue
        text = open(path, encoding="utf-8", errors="ignore").read()
        for sent in re.split(r"[。！？\n]", text):
            toks = tokenize(sent)
            if len(toks) >= 3:
                sentences.append(toks)
    print(f"句子: {len(sentences)}")

    t0 = time.time()
    model = Word2Vec(sentences, vector_size=dim, window=5,
                     min_count=min_count, workers=4,
                     epochs=epochs, sg=0)
    print(f"训练: {time.time()-t0:.0f}s, 词表 {len(model.wv.index_to_key)}")
    return model


# ── 3. 存库 ──
def store(model, db: str = _DB, dim: int = _DIM):
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE IF NOT EXISTS word_vectors("
                 "word TEXT PRIMARY KEY, vector BLOB, dim INT)")
    words = model.wv.index_to_key
    rows = [(w, model.wv[w].astype(np.float32).tobytes(), dim)
            for w in words]
    with conn:
        conn.executemany("INSERT OR REPLACE INTO word_vectors VALUES (?,?,?)",
                         rows)
    conn.close()
    print(f"存入 {len(rows)} 词向量 → {db}")


# ── 4. 查询 ──
class VectorSpace:
    """语义近邻查询: 加载全量向量到内存, numpy 批量余弦"""

    def __init__(self, db: str = _DB):
        self.conn = sqlite3.connect(db)
        self._words = None
        self._matrix = None

    def _load(self):
        if self._matrix is not None:
            return
        t0 = time.time()
        rows = self.conn.execute("SELECT word, vector FROM word_vectors").fetchall()
        self._words = [w for w, _ in rows]
        self._matrix = np.vstack([np.frombuffer(v, dtype=np.float32)
                                  for _, v in rows])
        print(f"向量载入: {len(self._words)} 词, {time.time()-t0:.1f}s")

    def neighbors(self, word: str, top_k: int = 10) -> list:
        """返回 [(邻居词, 余弦相似度)]"""
        self._load()
        if word not in self._words:
            return []
        idx = self._words.index(word)
        q = self._matrix[idx]
        norms = np.linalg.norm(self._matrix, axis=1)
        sims = (self._matrix @ q) / (norms * np.linalg.norm(q) + 1e-9)
        order = np.argsort(-sims)
        out = []
        for i in order:
            if self._words[i] == word:
                continue
            out.append((self._words[i], float(sims[i])))
            if len(out) >= top_k:
                break
        return out

    def analogies(self, a, b, c, top_k=5):
        """类比推理: a 之于 b 就像 c 之于 ?  (b - a + c)"""
        self._load()
        try:
            va = self._matrix[self._words.index(a)]
            vb = self._matrix[self._words.index(b)]
            vc = self._matrix[self._words.index(c)]
        except ValueError:
            return []
        target = vb - va + vc
        norms = np.linalg.norm(self._matrix, axis=1)
        sims = (self._matrix @ target) / (norms * np.linalg.norm(target) + 1e-9)
        order = np.argsort(-sims)
        out = []
        for i in order:
            if self._words[i] in (a, b, c):
                continue
            out.append((self._words[i], float(sims[i])))
            if len(out) >= top_k:
                break
        return out


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "train"
    if mode == "train":
        m = train()
        store(m)
    elif mode == "query":
        vs = VectorSpace()
        for w in sys.argv[2:]:
            ns = vs.neighbors(w, 5)
            if ns:
                print(f"「{w}」近邻: " +
                      " ".join(f"{n}({s:.2f})" for n, s in ns))
            else:
                print(f"「{w}」: 词表无此词")
