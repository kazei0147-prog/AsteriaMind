"""
vector_space.py — AM 的向量空间 (黑盒语义层)
=============================================
从语料训练 word2vec → 存 SQLite → 提供语义近邻查询

哲学 (2026-09-02 审计后修正):
  黑盒(向量空间) = 快而糙的 grounding: 应建立在真实大规模中文向量底座上
                   (fastText / 腾讯等), 而非 68万字自训。
  白盒(符号图谱) = 独立"法庭": 验证 / 纠错 / 细粒度知识, 能不同意黑盒。
  ★ 关键修正: 白盒 IS_A 边【禁止】灌进黑盒训练 (那是循环论证 + 错误放大),
    黑盒训练只吃语料; 白盒边只作验证约束 (court) 或可选的特化约束。

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
    """白盒知识 → 句子 (地球 是 行星)。

    ⚠️ 2026-09-02 审计后: 此函数【不再】喂进黑盒训练 (那是污染 + 循环论证)。
    保留作「特化约束源」: 供白盒模块把 IS_A / 非IS_A 当 ATTRACT/REPEL 约束,
    施加在黑盒向量之上 (ATTRACT-REPEL / LEAR 思路), 做细粒度上下位特化。
    粗粒度 grounding 靠真实底座 (见 load_pretrained), 不需要此函数。
    """
    conn = sqlite3.connect(db)
    rows = conn.execute(
        "SELECT source, relation, target FROM directed_edges "
        "WHERE relation IN ('IS_A','CAN','NOT_CAN','HAS','EATS','LIVES_IN',"
        "'CAUSES','NOT_CAUSES','OPPOSITE') "
        "AND LENGTH(source) <= 8 AND LENGTH(target) <= 8"
    ).fetchall()
    conn.close()
    rel_word = {"IS_A": "是", "CAN": "能够", "NOT_CAN": "不能",
                "HAS": "拥有", "EATS": "吃", "LIVES_IN": "生活在",
                "CAUSES": "导致", "NOT_CAUSES": "不会导致",
                "OPPOSITE": "与"}
    # ★ v3.9: 低频词语义增强 — 元关系边重复句式 (word2vec 里重复=提高权重)
    #   元常识词只出现 1-2 次 → 向量挤成 0.98 相似团 (学不出区分度)
    #   重复后 天上下雨↔地面变湿 才能真正在向量空间靠近
    REPEAT = {"CAUSES": 8, "NOT_CAUSES": 8, "OPPOSITE": 8}
    sents = []
    for s, r, t in rows:
        if r in rel_word:
            n = REPEAT.get(r, 1)
            for _ in range(n):
                if r == "OPPOSITE":
                    sents.append([s, rel_word[r], t, "相反"])
                    sents.append([t, rel_word[r], s, "相反"])
                else:
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
    # ★ 2026-09-02 审计修正: 移除「白盒边灌训练」(原 _named_edge_sentences)。
    #   审计发现: 那会让黑盒 = 白盒的向量化压缩版 → 双盒不独立, "法庭"退化为自言自语,
    #   且 27% 旁支泄漏把白盒错误放大进黑盒。黑盒训练只吃语料。
    #   白盒 IS_A 边的正确用途 = 验证约束(court) / 可选特化约束, 见 load_pretrained + 白盒模块。
    print(f"句子: {len(sentences)} (纯语料, 无白盒污染)")

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


# ── 3.5 加载真实底座 (2026-09-02 审计后新增) ──
def load_pretrained(vec_path: str, db: str = _DB, topn: int = None,
                    dim: int = None):
    """用真实大规模中文向量 (fastText / 腾讯 .vec 或 .vec.gz) 替换 word_vectors 表。

    审计结论: AM 原 word2vec 只在 68万字语料上自训 → 饿死; 且把白盒边灌进训练 → 污染。
    正确底座是真实大语料预训练向量 (本机已下 fastText cc.zh.300.vec.gz,
    在 59 概念外部真值测试上 AUC=0.82)。本函数流式读取, 维度以文件为准 (不限 128)。

    ⚠️ 此操作 REPLACE word_vectors 表 (清空旧向量), 调用前请确认已备份。
    """
    import gzip
    opener = gzip.open if vec_path.endswith(".gz") else open
    mode = "rt" if vec_path.endswith(".gz") else "r"
    n, kept = 0, 0
    rows, dim_actual = [], dim
    t0 = time.time()
    with opener(vec_path, mode, encoding="utf-8", errors="ignore") as f:
        f.readline()  # header: "n_words dim"
        for line in f:
            n += 1
            sp = line.rstrip("\n").split(" ")
            if len(sp) < 3:
                continue
            vec = np.array(sp[1:], dtype=np.float32)
            if dim_actual is None:
                dim_actual = int(vec.shape[0])
            elif vec.shape[0] != dim_actual:
                continue
            rows.append((sp[0], vec.tobytes(), dim_actual))
            kept += 1
            if topn and kept >= topn:
                break
    conn = sqlite3.connect(db)
    conn.execute("DROP TABLE IF EXISTS word_vectors")
    conn.execute("CREATE TABLE word_vectors("
                 "word TEXT PRIMARY KEY, vector BLOB, dim INT)")
    with conn:
        conn.executemany("INSERT OR REPLACE INTO word_vectors VALUES (?,?,?)", rows)
    conn.close()
    print(f"载入真实底座: {kept} 词 / {dim_actual}维, 扫 {n} 行, 用时 {time.time()-t0:.0f}s → {db}")
    return kept


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
        # ★ v3.7: 过滤纯英文 (防止 GEB 残留英文术语污染联想/缺口想法)
        #   至少含一个中文字符
        rows = [(w, v) for w, v in rows
                if any('\u4e00' <= ch <= '\u9fff' for ch in w)]
        self._words = [w for w, _ in rows]
        if rows:
            self._matrix = np.vstack([np.frombuffer(v, dtype=np.float32)
                                      for _, v in rows])
        else:
            self._matrix = np.zeros((0, 0), dtype=np.float32)
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

    def _pair_sim(self, a: str, b: str) -> float:
        """两个词的余弦相似度 (锚点监控用)"""
        self._load()
        try:
            ia, ib = self._words.index(a), self._words.index(b)
            va, vb = self._matrix[ia], self._matrix[ib]
            return float(np.dot(va, vb) /
                         (np.linalg.norm(va) * np.linalg.norm(vb) + 1e-9))
        except ValueError:
            return -1.0

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
    elif mode == "loadpretrained":
        p = sys.argv[2] if len(sys.argv) > 2 else None
        tn = int(sys.argv[3]) if len(sys.argv) > 3 else None
        if not p:
            print("用法: python vector_space.py loadpretrained <vec_path[.gz]> [topn]")
        else:
            load_pretrained(p, topn=tn)
    elif mode == "query":
        vs = VectorSpace()
        for w in sys.argv[2:]:
            ns = vs.neighbors(w, 5)
            if ns:
                print(f"「{w}」近邻: " +
                      " ".join(f"{n}({s:.2f})" for n, s in ns))
            else:
                print(f"「{w}」: 词表无此词")
