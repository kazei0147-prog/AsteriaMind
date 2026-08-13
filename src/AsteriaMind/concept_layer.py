"""
concept_layer.py — 概念层 (ConceptLayer) ★ v3.7

向量空间的正式归属 — 设想架构的 Concept 层
  多模态输入 → 概念层(统一语义空间) → 决策/推理/语言

防偏移三件套 (白盒验证黑盒 — 用户原则):
  ① 锚点监控: 核心概念对距离体检 (训练后检测漂移)
  ② 白盒校验: 命名边 ↔ 向量近邻 一致性率 (信念校验直觉)
  ③ 唯一入口: 其他层禁止直连 VectorSpace (物理防流浪)

★ v3.9 ID-018: belief_check 双向判读 (进化哲学 — 无绝对真理层)
  方向 A (白盒→黑盒): 命名边验证向量近邻 — 黑盒是否贴合白盒 (黑盒质量)
  方向 B (黑盒→白盒): 向量强相关验证命名边 — 黑盒新涌现是否被白盒沉淀
                        (白盒知识缺口 / 陈旧边候选)
  双向: 白盒可被黑盒推翻 — 不是白盒单向当尺子

用法:
  cl = ConceptLayer(star_map)
  cl.neighbors("企鹅")    语义近邻 (推理/可视化)
  cl.vocab()              词表 (决策层主语提取)
  cl.belief_check()       方向A: 白盒校验黑盒 (防偏移体检)
  cl.emergence_check()    方向B: 黑盒校验白盒 (新涌现/陈旧检测)
  cl.dual_check()         双向判读汇总 (HealthMonitor 数据源)
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
        """方向 A (白盒→黑盒): 抽命名边 (白盒信念), 验证 向量近邻 (黑盒直觉) 一致率

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

    # ── ★ v3.9 ID-018: 方向 B (黑盒→白盒): 黑盒新涌现检验白盒 ──
    def emergence_check(self, sample: int = 15,
                        sim_threshold: float = 0.7) -> dict:
        """黑盒新涌现 vs 白盒沉淀 — 找出"黑盒直觉很强但白盒没跟上"的对

        原理: 向量近邻相似度 ≥ 阈值 (黑盒强直觉) 但星图无命名边 → 两种可能:
          1. 白盒知识缺口 (黑盒从新语料涌现出白盒还没沉淀的知识)
          2. 白盒陈旧边候选 (黑盒新语义已偏移, 白盒旧边该被复核)
        这是"白盒可被黑盒推翻"的检测器 — belief_check 的反向
        """
        vs = self._load()
        # 从命名边 source 抽种子词 (保证是系统关心的实体)
        rows = self.star_map.conn.execute(
            "SELECT DISTINCT source FROM directed_edges "
            "WHERE relation IN ('IS_A','CAN','HAS','EATS','LIVES_IN') "
            "AND length(source)<=6 ORDER BY RANDOM() LIMIT ?",
            (sample,)).fetchall()
        seeds = [r[0] for r in rows]
        emergent = []
        checked = 0
        for w in seeds:
            if not w:
                continue
            try:
                ns = vs.neighbors(w, top_k=10)
            except Exception:
                continue
            for n, sim in ns:
                if sim < sim_threshold or n == w:
                    continue
                checked += 1
                # 白盒是否有该 (w→n) 命名边
                has_edge = self.star_map.conn.execute(
                    "SELECT 1 FROM directed_edges "
                    "WHERE source=? AND target=? LIMIT 1",
                    (w, n)).fetchone()
                if not has_edge:
                    emergent.append({"pair": f"{w}≈{n}",
                                     "sim": round(sim, 3)})
        return {"emergent_count": len(emergent),
                "emergent_pairs": emergent[:10],
                "seeded": len(seeds), "strong_links": checked,
                "threshold": sim_threshold}

    # ── ★ v3.9 ID-018: 双向判读汇总 (HealthMonitor 数据源) ──
    def dual_check(self, sample: int = 20) -> dict:
        """双向判读: 白盒验黑盒 + 黑盒验白盒 — 无单向真理

        返回:
          whitebox→blackbox: 方向A (黑盒贴合度, 低=黑盒质量问题)
          blackbox→whitebox: 方向B (白盒缺口/陈旧, 高=白盒该被复核)
          verdict: 综合健康判断
        """
        a = self.belief_check(sample=sample)
        b = self.emergence_check(sample=max(sample // 2, 8))
        # 综合判定 (预警等级驱动, 对接 ID-009 HealthMonitor)
        consistency = a["consistency"]
        emergent = b["emergent_count"]
        notes = []
        if consistency < 0.5:
            notes.append("方向A预警: 黑盒贴合白盒差 — 向量可能漂移/训练不足")
        if emergent >= 3:
            notes.append(f"方向B预警: 白盒有 {emergent} 个缺口/陈旧候选 — 黑盒新涌现未被沉淀")
        level = "normal"
        if consistency < 0.5 or emergent >= 3:
            level = "warning"
        if consistency < 0.3 and emergent >= 5:
            level = "critical"
        return {
            "direction_a_whitebox_to_blackbox": {
                "consistency": consistency, "checked": a["checked"],
                "hits": a["hits"], "misses": a["misses"]},
            "direction_b_blackbox_to_whitebox": {
                "emergent_count": emergent,
                "emergent_pairs": b["emergent_pairs"],
                "seeded": b["seeded"], "threshold": b["threshold"]},
            "verdict": {"level": level, "notes": notes},
        }

    # ── 健康 (registry 用) ──
    def health(self) -> float:
        try:
            bc = self.belief_check(sample=10)
            ac = self.anchor_check()
            return round(bc["consistency"] * 0.7
                         + (1.0 if not ac["drifted"] else 0.3) * 0.3, 2)
        except Exception:
            return 0.3
