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

# 虚词停用 — 共现频繁但无语义, 学它们会污染近邻
_STOPWORDS = frozenset(
    "的 了 是 在 我 你 他 她 它 我们 你们 他们 她们 它们 自己 大家 人们 "
    "这 那 这些 那些 这个 那个 这里 那里 什么 怎么 为什么 如何 多少 "
    "一个 一种 一些 之一 的话 一样 似的 之时 之后 而已 只是 已经 现在 "
    "一定 真的 大概 也许 可能 或许 似乎 看来 其实 不过 当然 因此 于是 "
    "然后 此后 其中 及其 以及 或者 另外 除了 包括 关于 根据 通过 由于 "
    "因为 所以 如果 虽然 但是 可是 然而 而是 而且 还是 就是 便是 则是 "
    "不是 没有 可以 应该 必须 能够 需要 不能 不会 不要 开始 结束 继续 "
    "之下 之上 之中 之间 之际 致力于 方便 短杠 一方面 另一方面 "
    "尽管 即使 无论 不管 只要 只有 除非 不但 不仅 既 又 也 还 都 很 更 "
    "最 太 极 非常 相当 比较 稍微 有些 有点 常常 往往 通常 一般 有时 "
    "每次 再次 首次 最初 最早 最后 最终 首先 然后 接着 随后 同时 另外".split()
)


# ── 1. 分词 (jieba) ──
def tokenize(text: str) -> list:
    """jieba 分词: 保留中文词 + 英文词, 过滤单字/纯数字/虚词"""
    import jieba
    text = re.sub(r"[^\u4e00-\u9fff\w]", " ", text)
    words = []
    for w in jieba.cut(text):
        w = w.strip()
        if len(w) >= 2 and not re.match(r"^\d+$", w) \
                and w not in _STOPWORDS:
            words.append(w)
    return words


def _named_edge_sentences(db: str = _DB) -> list:
    """白盒知识反哺: 命名边 → 句子 (地球 是 行星 → 加入训练语料)

    让我们教她的知识 (IS_A/CAN/HAS/EATS...) 变成向量学习的养料
    """
    conn = sqlite3.connect(db)
    rows = conn.execute(
        "SELECT source, relation, target FROM directed_edges "
        "WHERE relation IN ('IS_A','CAN','NOT_CAN','HAS','EATS','LIVES_IN') "
        "AND LENGTH(source) <= 8 AND LENGTH(target) <= 8"
    ).fetchall()
    conn.close()
    rel_word = {"IS_A": "是", "CAN": "能够", "NOT_CAN": "不能",
                "HAS": "拥有", "EATS": "吃", "LIVES_IN": "生活在"}
    sents = []
    for s, r, t in rows:
        if r in rel_word:
            sents.append([s, rel_word[r], t])
            sents.append([t, rel_word[r], s])  # 双向, 增加共现
    print(f"种子句子: {len(sents)}")
    return sents


# ── 2. 训练 ──
def train(corpus_dir: str = _CORPUS_DIR, dim: int = _DIM,
          min_count: int = 1, epochs: int = 15):
    """扫描语料 + 种子知识 → 分句分词 → 训练 word2vec (CBOW)"""
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
    # 白盒知识反哺: 命名边句子加入语料 (核心词重复出现 → 向量可靠)
    sentences += _named_edge_sentences()
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
