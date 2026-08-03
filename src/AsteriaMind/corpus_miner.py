"""
CorpusMiner — 语料矿工 (AsteriaMind v3.6)

把本地语料从"联想素材"变成"知识来源":
  文本 → 句式模板提取三元组 → 频次确认 → 命名边

句式模板 (中文):
  X是Y / X属于Y            → IS_A
  X吃Y / X捕食Y            → EATS
  X生活在Y / X栖息在Y       → LIVES_IN
  X具有Y / X拥有Y / X有Y    → HAS
  X能Y / X可以Y            → CAN
  X不能Y / X不会Y           → NOT_CAN
  X围绕Y环绕               → ORBITS

确认规则:
  同一三元组出现 ≥2 次 → 直接存命名边 (confirmed)
  出现 1 次             → 跳过 (噪声过滤, 不进假说池)

设计原则: 宁可少学, 不可学错 — 低质量知识比没有更糟
"""

import os
import re
from collections import Counter

# 句式模板: (正则, 关系, 主语组, 宾语组)
PATTERNS = [
    (r'([\u4e00-\u9fff]{2,8}?)是([\u4e00-\u9fff]{2,12})', "IS_A", 1, 2),
    (r'([\u4e00-\u9fff]{2,8}?)属于([\u4e00-\u9fff]{2,12})', "IS_A", 1, 2),
    (r'([\u4e00-\u9fff]{2,8}?)吃([\u4e00-\u9fff]{2,8})', "EATS", 1, 2),
    (r'([\u4e00-\u9fff]{2,8}?)捕食([\u4e00-\u9fff]{2,8})', "EATS", 1, 2),
    (r'([\u4e00-\u9fff]{2,8}?)生活在([\u4e00-\u9fff]{2,10})', "LIVES_IN", 1, 2),
    (r'([\u4e00-\u9fff]{2,8}?)栖息在([\u4e00-\u9fff]{2,10})', "LIVES_IN", 1, 2),
    (r'([\u4e00-\u9fff]{2,8}?)具有([\u4e00-\u9fff]{2,8})', "HAS", 1, 2),
    (r'([\u4e00-\u9fff]{2,8}?)拥有([\u4e00-\u9fff]{2,8})', "HAS", 1, 2),
    (r'([\u4e00-\u9fff]{2,8}?)不能([\u4e00-\u9fff]{2,8})', "NOT_CAN", 1, 2),
    (r'([\u4e00-\u9fff]{2,8}?)不会([\u4e00-\u9fff]{2,8})', "NOT_CAN", 1, 2),
    (r'([\u4e00-\u9fff]{2,8}?)围绕([\u4e00-\u9fff]{2,8})', "ORBITS", 1, 2),
]

# 主语过滤 (复用 active_learner 的实体质量思路)
_BAD_SUBJECT = {
    '我们', '你们', '他们', '她们', '它们', '自己', '大家', '人们',
    '这', '那', '它', '他', '她', '我', '你', '这些', '那些',
    '什么', '怎么', '为什么', '如何', '一个', '一种',
    '就是', '则是', '便是', '其是', '可是', '但是', '还是',
    '所以', '因为', '如果', '而且', '以及', '或者', '另外',
    '首先', '然后', '最后', '最初', '最早', '可能', '也许',
    '当然', '其实', '几乎', '通常', '一般', '主要',
    '特别是', '尤其', '尤其以',
}
_BAD_OBJECT = {
    '什么', '怎么', '为什么', '这样', '那样', '一个', '吗', '呢',
    '东西', '事情', '问题', '时候', '地方', '方式', '方法',
    '之一', '的话', '一样', '这样', '那样', '所以',
}
# 副词前缀: "我只是" "特别是" "就更" → 主语残片
_BAD_SUBJ_PREFIX = ('只', '就', '也', '还', '更', '都', '又', '很', '太',
                    '特别', '尤其', '主要', '有些', '许多', '一些', '多数',
                    '然后', '甚至', '几乎', '大约', '也许', '或许', '大概',
                    '其中', '关于', '对于')
# 形容词/动词尾: "激动不已" "微不足道的" → 宾语是描述不是实体
_BAD_OBJ_TAIL = ('的', '地', '得', '不已', '万分', '极了', '一样', '似的',
                 '之一', '之中', '之一', '出来的', '起来的')
# IS_A 宾语动词尾: "得知" "工作" → 动词短语
_BAD_OBJ_VERB_TAIL = ('得', '到', '来', '去', '走', '看', '说', '想', '知道',
                      '工作', '存在', '发生', '进行', '成为', '属于', '出现',
                      '开始', '结束', '使用', '表示', '表明', '意味着')


class CorpusMiner:
    def __init__(self, star_map, corpus_dir: str = "corpus"):
        self.star_map = star_map
        self.corpus_dir = corpus_dir

    def mine(self, min_confirm: int = 2, co_support: float = 0.25) -> dict:
        """扫描语料 → 提取 → 确认 → 存命名边

        确认条件 (任一):
          a. 同一三元组出现 ≥ min_confirm 次 (频次确认)
          b. (s,o) 在 co_text 联想能量 ≥ co_support (黑盒验证)

        返回: {triples_found, confirmed, skipped, by_relation}
        """
        result = {"triples_found": 0, "confirmed": 0,
                  "skipped": 0, "by_relation": {}}
        counter: Counter = Counter()  # (subj, rel, obj) → count

        # 1. 扫描所有 .txt 语料
        if not os.path.isdir(self.corpus_dir):
            return result
        for fname in os.listdir(self.corpus_dir):
            if not fname.endswith('.txt'):
                continue
            path = os.path.join(self.corpus_dir, fname)
            try:
                with open(path, 'r', encoding='utf-8', errors='ignore') as f:
                    text = f.read()
            except Exception:
                continue
            # 2. 逐句提取
            for sent in re.split(r'[。！？\n]', text):
                for pat, rel, g_subj, g_obj in PATTERNS:
                    m = re.search(pat, sent)
                    if not m:
                        continue
                    s = m.group(g_subj).strip()
                    o = m.group(g_obj).strip()
                    if not self._valid(s, o, rel):
                        continue
                    counter[(s, rel, o)] += 1

        # 3. 频次确认 + 黑盒验证 + 白盒验证
        for (s, rel, o), cnt in counter.items():
            result["triples_found"] += 1
            support = self._co_text_support(s, o)
            # 宾语必须是已知概念 (防止 '我的生日' '元编码' 这种碎片)
            if not self._known_concept(o):
                result["skipped"] += 1
                continue
            if cnt >= min_confirm or support >= co_support:
                self.star_map.store(s, rel, o, "confirmed",
                                    f"corpus_miner: 频次{cnt}, 联想能量{support:.2f}")
                result["confirmed"] += 1
                result["by_relation"][rel] = result["by_relation"].get(rel, 0) + 1
            else:
                result["skipped"] += 1
        return result

    def _valid(self, s: str, o: str, rel: str) -> bool:
        """实体质量: 过短/代词/残片 → 拒绝"""
        if not s or not o or s == o:
            return False
        if len(s) < 2 or len(o) < 2:
            return False
        if s in _BAD_SUBJECT or o in _BAD_OBJECT:
            return False
        # 主语不能带"的" (通常是形容词短语碎片)
        if '的' in s:
            return False
        # 主语不能以副词前缀开头 ("我只是"/"特别是")
        if any(s.startswith(p) for p in _BAD_SUBJ_PREFIX):
            return False
        # 宾语不能是纯虚词
        if o in _BAD_SUBJECT:
            return False
        # 主语和宾语必须含中文
        if not re.search(r'[\u4e00-\u9fff]', s) or not re.search(r'[\u4e00-\u9fff]', o):
            return False
        # IS_A 宾语不能是代词性短语
        if rel == "IS_A" and any(o.startswith(p) for p in ('这个', '那个', '一种', '一个')):
            return False
        # 宾语不能以形容词/动词尾收 (描述性短语不是实体)
        if any(o.endswith(t) for t in _BAD_OBJ_TAIL):
            return False
        if rel == "IS_A" and any(o.endswith(t) for t in _BAD_OBJ_VERB_TAIL):
            return False
        # 宾语过长 → 大概率是句子碎片
        if len(o) > 10:
            return False
        return True

    def _co_text_support(self, s: str, o: str) -> float:
        """黑盒验证: (s,o) 在 co_text 联想中的共现能量"""
        e = self.star_map.conn.execute(
            "SELECT energy FROM directed_edges "
            "WHERE source=? AND target=? AND relation='co_text' LIMIT 1",
            (s, o)).fetchone()
        return e[0] if e else 0.0

    def _known_concept(self, o: str) -> bool:
        """白盒验证: 宾语必须是星图里的已知概念
        (在联想词汇表中作为词出现, 而非句子碎片/短语)
        """
        row = self.star_map.conn.execute(
            "SELECT SUM(energy) FROM directed_edges "
            "WHERE source=? AND relation='co_text'", (o,)).fetchone()
        return bool(row and row[0] and row[0] >= 0.5)
