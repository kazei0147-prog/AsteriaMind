"""
language_model.py — AM 自己的语言层 (统计生成, 非模板)

哲学: 语言能力跟知识一样, 从她读过的句子里长出来
  - 不写模板 (那是我们定义她怎么说话)
  - 从 language_traces (34360 句 GEB) 挖"句式骨架"
  - 回答时按概率采样骨架 → 填充实体 → 她的句子

骨架 = 真实句子去掉实体后的形状 (保留所有连接成分)
  "企鹅虽然不会飞行" → 实体: 企鹅/飞行 → 骨架: "{S}虽然不会{O}"
  回答 "蛇虽然不会咀嚼" → 采样到该骨架 → "蛇虽然不会咀嚼"

骨架池随语料成长: 喂对话/百科语料 → 骨架更丰富更自然
"""

import re
import sqlite3
from collections import Counter

_DB = "asteriamind.db"


def _has_chinese(s: str) -> bool:
    """★ v3.7: 至少含一个中文字符 — 防止英文/拼音混入骨架"""
    return any('\u4e00' <= ch <= '\u9fff' for ch in s)

# 关系词 → 星图关系 (用于骨架分类)
# ★ v3.9 F16: 加入 CAUSES 因果 (瓶颈一: 常识骨架)
_REL_WORDS = {
    "IS_A":     ["是", "属于", "作为", "被视为"],
    "CAN":      ["能", "会", "可以", "能够", "善于", "擅长"],
    "NOT_CAN":  ["不能", "不会", "无法", "难以", "不具备"],
    "HAS":      ["有", "拥有", "具有", "长着"],
    "EATS":     ["吃", "捕食", "以", "进食"],
    "LIVES_IN": ["生活在", "居住在", "栖息在", "住在", "生存于"],
    "ORBITS":   ["绕着", "围绕", "环绕"],
    "CAUSES":   ["导致", "引起", "造成", "引发", "使得", "致使", "带来"],
    "NOT_CAUSES": ["不会导致", "不会引起", "不会造成", "不导致", "不引起"],
    "OPPOSITE": ["相反", "对立", "相对立", "相反于"],
}
_REL_LOOKUP = {}
for _rel, _words in _REL_WORDS.items():
    for _w in _words:
        _REL_LOOKUP[_w] = _rel
# 按长度降序排序 (最长匹配优先: "生活在" 优先于 "在")
_REL_PATTERN = "|".join(sorted(_REL_LOOKUP.keys(), key=len, reverse=True))

# 骨架允许的修饰词白名单 (脏骨架过滤)
_ALLOWED_CHARS = set(
    "的 了 也 还 都 就 并 而 且 很 更 最 一 种 类 般 似 乎 其实 虽 但 因 为 "
    "所 以 因 此 并 且 不 仅 而 且 大 概 可 能 会 能 要 应 该 常 常 往 往 "
    "通 常 主 要 正 是 已 经 曾 经 将 会 无 法 难 以 不 具 备 拥 有 生 活 "
    "在 栖 息 属 于 被 视 作 为 绕 着 围 绕 环 绕 吃 捕 食 进 食 长 着 "
    "不 会 不 能 可 以 能 够 善 于 擅 长 拥 有 具 有 "
    "导 致 引 起 造 成 引 发 使 得 致 使 带 来 会 导 致 不 会 引 起 "
    "相 反 对 立 相 对 立 相 反 于".split())



class LanguageModel:
    """统计语言模型: 骨架挖掘 + 概率采样生成"""

    def __init__(self, db: str = _DB, vocab: set = None):
        self.conn = sqlite3.connect(db)
        self.vocab = vocab or self._load_vocab()
        self._pool = None  # {relation: [(skeleton, count)]}

    def _load_vocab(self) -> set:
        """词表: 向量词表 + 命名实体 (实体识别用)
        ★ v3.7: 过滤纯英文/英文为主的词 — GEB 残留英文术语污染骨架池
        """
        v = set()
        try:
            for (w,) in self.conn.execute(
                    "SELECT word FROM word_vectors").fetchall():
                if len(w) >= 2 and _has_chinese(w):
                    v.add(w)
        except Exception:
            pass
        for (w,) in self.conn.execute(
                "SELECT DISTINCT source FROM directed_edges").fetchall():
            if len(w) >= 2 and _has_chinese(w):
                v.add(w)
        return v

    # ── 1. 骨架挖掘 ──
    def mine(self, min_count: int = 1) -> dict:
        """从 language_traces 挖句式骨架 → 按关系分类统计
        ★ v3.8: user_dialogue 加权 ×5 — 对话句式是"目标语言", 优先采到
        """
        pool = Counter()
        n_sent = 0
        rows = self.conn.execute(
            "SELECT sentence, sentence_type FROM language_traces").fetchall()
        for sent, stype in rows:
            n_sent += 1
            # 对话语料加权: 用户的话是她该学的说话方式 (×5)
            w = 5 if stype == "user_dialogue" else 1
            for m in re.finditer(
                    r"([^，。；！？]{1,10})(" + _REL_PATTERN +
                    r")([^，。；！？]{1,10})", sent):
                pre, rel, post = m.groups()
                rel_type = _REL_LOOKUP[rel]
                s_ent = self._find_entity(pre)
                o_ent = self._find_entity(post)
                if not s_ent or not o_ent:
                    continue
                if s_ent == o_ent:
                    continue
                skeleton = (pre.replace(s_ent, "{S}") + rel
                            + post.replace(o_ent, "{O}"))
                # 骨架太碎 (只剩关系词) 不要
                if skeleton.count("{") < 2:
                    continue
                # ★ 脏骨架过滤: 除 {S}/{O}/关系词/白名单修饰词外, 丢弃
                leftover = skeleton.replace("{S}", "").replace("{O}", "")
                leftover = leftover.replace(rel, "")
                if any(ch not in _ALLOWED_CHARS for ch in leftover):
                    continue
                pool[(rel_type, skeleton)] += w
        # 存统计
        self._pool = {rel: [] for rel in _REL_WORDS}
        for (rel, sk), c in pool.items():
            if c >= min_count:
                self._pool[rel].append((sk, c))
        print(f"扫描 {n_sent} 句 → 骨架池: " +
              ", ".join(f"{rel}×{len(v)}" for rel, v in self._pool.items()
                        if v))
        return self._pool

    def _find_entity(self, text: str) -> str:
        """在文本里找最长词表匹配 (实体识别)
        ★ v3.7: 防御性二次校验 — entity 必须含中文, 防止英文混入骨架
        """
        best = ""
        for w in range(min(8, len(text)), 1, -1):
            for i in range(len(text) - w + 1):
                kw = text[i:i + w]
                if (kw in self.vocab and len(kw) > len(best)
                        and _has_chinese(kw)):
                    best = kw
            if best:
                break
        return best

    # ── 2. 概率采样生成 ──
    def speak(self, edges: list, max_sent: int = 3) -> str:
        """给定边集合 → 采样骨架 → 生成句子

        edges: [{source, relation, target}, ...]
        返回: 自然语言 (从她学过的句式里采样, 非模板)
        """
        if self._pool is None:
            self.mine()
        sentences = []
        for e in edges[:max_sent]:
            rel = e["relation"]
            if rel not in self._pool or not self._pool[rel]:
                continue
            sk, c = self._sample(self._pool[rel])
            try:
                s = sk.format(S=e["source"], O=e["target"])
            except Exception:
                continue
            if s and s not in sentences:
                sentences.append(s)
        return "，".join(sentences) + "。" if sentences else ""

    def _sample(self, pool: list):
        """按出现频次加权采样 (概率+随机)"""
        total = sum(c for _, c in pool)
        import random
        r = random.random() * total
        acc = 0
        for sk, c in pool:
            acc += c
            if r <= acc:
                return sk, c
        return pool[0]


if __name__ == "__main__":
    lm = LanguageModel()
    lm.mine()
    # 测试: 采样企鹅的边
    edges = [
        {"source": "企鹅", "relation": "IS_A", "target": "鸟类"},
        {"source": "企鹅", "relation": "NOT_CAN", "target": "飞行"},
        {"source": "企鹅", "relation": "CAN", "target": "游泳"},
        {"source": "企鹅", "relation": "HAS", "target": "羽毛"},
    ]
    print()
    print("=== 采样生成 5 次 (每次不同) ===")
    for i in range(5):
        print(f"  {lm.speak(edges)}")
