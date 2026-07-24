"""
DreamModule — 低频创造系统 (AsteriaMind v3.2)

不是记忆——是想象。
从 CognitiveStarMap 中读取已有认知痕迹，产生未经验证的假设。

不直接修改星图——产出进入 HypothesisPool，等待用户验证。
"""
import time, random
from collections import defaultdict


class DreamModule:
    """
    梦境引擎——AM 的"想象力"。

    低频运行。从已有认知中生成:
      - 类比假说 (A 有特征 X, B 也是 A 的子类 → B 可能有 X?)
      - 传递推理 (A→B, B→C → A→C?)
      - 反向质疑 (所有 X 都是 Y, 那 Z 不是 X?)

    不做结论——丢进 HypothesisPool。
    """

    def __init__(self, star_map=None):
        self.star_map = star_map
        self.hypothesis_pool: list[dict] = []

    def dream(self) -> list[dict]:
        """
        执行一次梦境循环。

        返回: 本轮产生的假说列表 [{type, subject, predicate, object, confidence, reasoning}]
        """
        if not self.star_map or not hasattr(self.star_map, 'conn'):
            return []

        new_hypotheses = []

        # 1. 类比假说: 同聚类成员的属性传递
        analogies = self._dream_analogies()
        new_hypotheses.extend(analogies)

        # 2. 传递推理: A→B + B→C → A→C
        transitive = self._dream_transitive()
        new_hypotheses.extend(transitive)

        # 3. 反向质疑: 已知 A IS_A B, 但 A 有特征 C 而 B 类其他成员没有 → 标记
        anomalies = self._dream_anomalies()
        new_hypotheses.extend(anomalies)

        self.hypothesis_pool.extend(new_hypotheses)
        return new_hypotheses

    def _dream_analogies(self) -> list[dict]:
        """
        类比: 同聚类的成员可能共享属性。

        例: 猫 IS_A 哺乳动物, 狗 IS_A 哺乳动物, 海豚 IS_A 哺乳动物
            猫 CAN 喵, 狗 CAN 汪
            → 假说: 海豚 CAN 某种声音? (低置信)

        更实际:
            鸟 CAN 飞, 蝴蝶 CAN 飞
            → 同聚类"CAN::飞"还有谁? 如果发现蝙蝠 IS_A 哺乳动物, 推测蝙蝠 CAN 飞?
        """
        conn = self.star_map.conn
        hyps = []

        # 找共享 predicate+object 的聚类
        clusters = defaultdict(list)
        for row in conn.execute(
            "SELECT subj, pred, obj FROM cognitive_traces WHERE feedback='confirmed'"
        ):
            key = f"{row[1]}::{row[2]}"  # e.g. "IS_A::哺乳动物"
            clusters[key].append(row[0])

        # 对每个 ≥3 成员聚类, 找成员间的属性差异
        for key, members in clusters.items():
            pred, obj = key.split("::", 1)
            if len(members) < 2:
                continue

            # 找其中一个成员有但另一个成员没有的关系
            member_traits = defaultdict(set)
            for row in conn.execute(
                "SELECT subj, pred, obj FROM cognitive_traces WHERE feedback='confirmed'"
            ):
                if row[0] in members:
                    member_traits[row[0]].add((row[1], row[2]))

            # 传递: 成员 A 有特征 X, 成员 B 没有 → 假设 B 可能有 X
            for a in members:
                for b in members:
                    if a >= b:
                        continue
                    a_traits = member_traits.get(a, set())
                    b_traits = member_traits.get(b, set())
                    diff = a_traits - b_traits
                    for trait_pred, trait_obj in diff:
                        if trait_pred == pred and trait_obj == obj:
                            continue  # 就是聚类键本身, 跳过
                        hyps.append({
                            "type": "analogy",
                            "subject": b,
                            "predicate": trait_pred,
                            "object": trait_obj,
                            "confidence": 0.2,
                            "reasoning": f"{a} 有 [{trait_pred}] {trait_obj}, "
                                         f"{a} 和 {b} 都是 {obj}, "
                                         f"推测 {b} 也可能有 [{trait_pred}] {trait_obj}",
                            "status": "unverified",
                            "timestamp": time.time(),
                        })

        return hyps

    def _dream_transitive(self) -> list[dict]:
        """
        传递推理: A IS_A B, B IS_A C → A IS_A C。

        如果星图中已有 A→B, B→C, 但没有 A→C,
        生成低置信假说 A→C。
        """
        conn = self.star_map.conn
        hyps = []

        # 收集所有 IS_A 关系
        is_a_map = defaultdict(set)  # subj → {objects}
        for row in conn.execute(
            "SELECT subj, obj FROM cognitive_traces WHERE pred='IS_A' AND feedback='confirmed'"
        ):
            is_a_map[row[0]].add(row[1])

        for subj, direct_objs in is_a_map.items():
            for direct_obj in list(direct_objs):
                if direct_obj not in is_a_map:
                    continue
                # direct_obj 也有 IS_A 关系 → 传递
                for transitive_obj in is_a_map[direct_obj]:
                    if transitive_obj in direct_objs or transitive_obj == subj:
                        continue
                    # 检查是否已经直接存在
                    already_exists = any(
                        r[2] == transitive_obj
                        for r in conn.execute(
                            "SELECT * FROM cognitive_traces WHERE subj=? AND pred='IS_A' AND obj=?",
                            (subj, transitive_obj))
                    )
                    if not already_exists:
                        hyps.append({
                            "type": "transitive",
                            "subject": subj,
                            "predicate": "IS_A",
                            "object": transitive_obj,
                            "confidence": 0.3,
                            "reasoning": f"{subj} IS_A {direct_obj}, {direct_obj} IS_A {transitive_obj} → {subj} IS_A {transitive_obj}?",
                            "status": "unverified",
                            "timestamp": time.time(),
                        })

        return hyps

    def _dream_anomalies(self) -> list[dict]:
        """
        反向质疑: 聚类中某个成员的独有属性。

        例: 猫/狗/海豚都是哺乳动物。
            海豚 CAN 游泳 (独有)
            → 假说: 游泳是海豚的特殊能力? (不是所有哺乳动物都会)
            这个假说价值在于——标记为 anomaly, 不是错误, 是特征。
        """
        # 和 analogies 逻辑互补——analogies 找缺失属性, anomalies 找独有属性
        # 暂时复用 analogies 的聚类结构, 标记为 anomaly
        return []  # 第一阶段: 先跑通 analogies + transitive

    def get_pending_hypotheses(self, limit: int = 10) -> list[dict]:
        """获取待验证假说"""
        pending = [h for h in self.hypothesis_pool if h.get("status") == "unverified"]
        pending.sort(key=lambda h: h["confidence"], reverse=True)
        return pending[:limit]

    def verify_hypothesis(self, idx: int, accepted: bool) -> None:
        """
        验证假说: 用户确认/拒绝。

        确认 → 写入 cognitive_traces (confirmed)
        拒绝 → 标记为 corrected
        """
        if idx < 0 or idx >= len(self.hypothesis_pool):
            return
        hyp = self.hypothesis_pool[idx]
        if accepted and self.star_map:
            self.star_map.store(
                hyp["subject"], hyp["predicate"], hyp["object"],
                "confirmed",
                f"{hyp['subject']}{hyp['predicate']}{hyp['object']}"
            )
        hyp["status"] = "confirmed" if accepted else "corrected"
