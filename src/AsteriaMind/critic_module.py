"""
CriticModule — 内部批判者 (AsteriaMind v3.6)

灵感: Curiosity = H(prediction)
  高熵 = 不确定 = 好奇心 = 学习驱动力

角色:
  1. 每轮对话后扫描高熵实体 → 记录"我还不确定什么"
  2. 用户问高熵实体 → 诚实标注不确定性
  3. 离线循环优先学习高熵实体

熵计算:
  H(X) = -Σ p(rel_i) log p(rel_i)
  其中 p(rel_i) = 关系类型 i 的边数 / X 的总边数
  均匀分布 → 高熵 (知识模糊)
  单一边类型 → 低熵 (知识明确)
"""

import math


class CriticModule:
    def __init__(self, star_map, entropy_threshold: float = 0.8):
        self.star_map = star_map
        self.entropy_threshold = entropy_threshold
        self.uncertain_entities: dict[str, float] = {}  # entity → H
        self.skeptic_responses = [
            "说实话，关于{subject}我有点拿不准——我还没完全搞清楚它和其他东西的关系。",
            "{subject}这个，我的知识里还有些矛盾的地方，不敢说得太满。",
            "问得好……其实我对{subject}的认知还不够深，想了解更多才能给你确定答案。",
            "唔，{subject}？我现在脑子里的信息比较乱，需要再学一点。",
        ]

    def entropy_of(self, entity: str) -> float:
        """计算实体的预测熵 H(X)"""
        rows = self.star_map.conn.execute(
            "SELECT relation, COUNT(*) FROM directed_edges "
            "WHERE source=? AND relation IN ('IS_A','CAN','NOT_CAN','HAS','EATS','LIVES_IN') "
            "GROUP BY relation", (entity,)).fetchall()
        if not rows:
            return 1.0  # 无知识 = 最大熵
        total = sum(r[1] for r in rows)
        h = 0.0
        for _, count in rows:
            p = count / total
            h -= p * math.log(p) if p > 0 else 0
        # 归一化: 除以 log(最大可能类别数=6)
        return h / math.log(6) if total > 1 else 0.0

    def scan_uncertain(self, top_k: int = 10) -> list[dict]:
        """扫描全星图, 找出高熵实体 (知识模糊/矛盾的)"""
        self.uncertain_entities = {}
        entities = self.star_map.conn.execute(
            "SELECT DISTINCT source FROM directed_edges "
            "WHERE relation IN ('IS_A','CAN','NOT_CAN','HAS') LIMIT 500").fetchall()
        result = []
        for (e,) in entities:
            h = self.entropy_of(e)
            if h > self.entropy_threshold:
                self.uncertain_entities[e] = h
                result.append({"entity": e, "entropy": h})
        result.sort(key=lambda x: -x["entropy"])
        return result[:top_k]

    def check(self, entity: str) -> dict | None:
        """用户问实体时: 熵高吗? 要不要标注不确定性?"""
        h = self.entropy_of(entity)
        if h > self.entropy_threshold:
            import random
            return {
                "uncertain": True,
                "entropy": h,
                "preface": random.choice(self.skeptic_responses).format(subject=entity),
            }
        return None

    def learn_targets(self, top_k: int = 5) -> list[dict]:
        """给离线学习器: 高熵实体 = 优先学习目标"""
        return self.scan_uncertain(top_k=top_k)

    def summarize(self) -> dict:
        targets = self.scan_uncertain(top_k=5)
        return {
            "uncertain_count": len(self.uncertain_entities),
            "top_uncertain": targets,
            "threshold": self.entropy_threshold,
        }
