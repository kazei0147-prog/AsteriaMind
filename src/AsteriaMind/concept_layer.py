"""
concept_layer.py — 概念层 (ConceptLayer) ★ v3.7

向量空间的正式归属 — 设想架构的 Concept 层
  多模态输入 → 概念层(统一语义空间) → 决策/推理/语言

防偏移三件套 (白盒验证黑盒 — 用户原则):
  ① 锚点监控: 核心概念对距离体检 (训练后检测漂移)
  ② 白盒校验: 命名边 ↔ 向量近邻 一致性率 (信念校验直觉)
  ③ 唯一入口: 其他层禁止直连 VectorSpace (物理防流浪)

用法:
  cl = ConceptLayer(star_map)
  cl.neighbors("企鹅")    语义近邻 (推理/可视化)
  cl.vocab()              词表 (决策层主语提取)
  cl.belief_check()       白盒校验黑盒 (防偏移体检)
"""

from AsteriaMind.vector_space import VectorSpace


class ConceptLayer:
    """概念层: 统一语义空间 + 防偏移监控"""

    # 锚点对: 语义上应该接近的核心概念 (偏移检测基线)
    ANCHOR_PAIRS = [("哺乳动物", "爬行动物"), ("鸟类", "鱼类"),
                    ("行星", "恒星"), ("水果", "蔬菜"),
                    ("河流", "海洋"), ("器官", "组织")]

    def __init__(self, star_map):
        self.star_map = star_map
        self._vector = None
        self._baseline = None  # 锚点距离基线 (首次体检时记录)

    def _load(self):
        if self._vector is None:
            self._vector = VectorSpace()
            self._vector._load()
        return self._vector

    # ── 语义查询 (唯一入口) ──
    def neighbors(self, word: str, top_k: int = 10) -> list:
        return self._load().neighbors(word, top_k)

    def vocab(self) -> set:
        v = self._load()
        return set(v._words) if v._words else set()

    # ── 防偏移 ①: 锚点监控 ──
    def anchor_distances(self) -> dict:
        """锚点对距离: 语义相近的词 cos 应高 (接近 1)"""
        vs = self._load()
        out = {}
        for a, b in self.ANCHOR_PAIRS:
            out[f"{a}~{b}"] = round(vs._pair_sim(a, b), 3)
        return out

    def anchor_check(self) -> dict:
        """锚点体检: 当前距离 vs 基线 → 漂移报告"""
        cur = self.anchor_distances()
        if self._baseline is None:
            self._baseline = cur
            drift = 0.0
        else:
            drifts = [abs(cur[k] - self._baseline[k])
                      for k in cur if k in self._baseline]
            drift = max(drifts) if drifts else 0.0
        return {"distances": cur, "drift": round(drift, 3),
                "drifted": drift > 0.1}

    # ── 防偏移 ②: 白盒校验黑盒 ──
    def belief_check(self, sample: int = 20) -> dict:
        """抽命名边 (白盒信念), 验证 向量近邻 (黑盒直觉) 一致率

        星图说 "企鹅 IS_A 鸟类" → 向量里"鸟类"应该在"企鹅"近邻
        一致率低 = 向量漂移/训练不足 → 偏移信号
        """
        vs = self._load()
        rows = self.star_map.conn.execute(
            "SELECT source, target FROM directed_edges "
            "WHERE relation='IS_A' AND length(source)<=6 AND length(target)<=6 "
            "ORDER BY RANDOM() LIMIT ?", (sample,)).fetchall()
        hits = 0
        misses = []
        for s, t in rows:
            ns = vs.neighbors(s, top_k=20)
            names = [n for n, _ in ns]
            if t in names:
                hits += 1
            else:
                misses.append(f"{s}≈{t}")
        total = len(rows)
        return {"consistency": round(hits / total, 2) if total else 1.0,
                "checked": total, "hits": hits,
                "misses": misses[:5]}

    # ── 健康 (registry 用) ──
    def health(self) -> float:
        try:
            bc = self.belief_check(sample=10)
            ac = self.anchor_check()
            return round(bc["consistency"] * 0.7
                         + (1.0 if not ac["drifted"] else 0.3) * 0.3, 2)
        except Exception:
            return 0.3
