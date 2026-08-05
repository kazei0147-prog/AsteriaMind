"""
MemoryConsolidation — 低频记忆巩固 (AsteriaMind v3.2)

后台运行, 不响应请求。
只做三件事:
  1. 更新边权 (weight, confidence, decay)
  2. 发现 emergent categories (从 cognitive_traces 聚类)
  3. 修正矛盾连接

不是创造新知识——是整理已有认知。
"""
import time, math
from collections import defaultdict
from typing import Optional


class MemoryConsolidation:
    """
    记忆巩固引擎——AM 的"睡眠"。

    不创建新痕迹, 只从已有 cognitive_traces 中:
      - 发现 emergent clusters
      - 标记矛盾边
      - 衰减冷知识
    """

    def __init__(self, star_map=None):
        self.star_map = star_map
        self.clusters: dict[str, set] = {}       # cluster_id → {entities}
        self.cluster_centroids: dict[str, str] = {}  # cluster_id → central entity
        self.contradictions: list[dict] = []       # [(subj, pred, obj_a, obj_b), ...]
        self.last_run: float = 0

    def consolidate(self) -> dict:
        """
        执行一次完整的记忆巩固循环。

        返回: { clusters_found, contradictions_found, edges_decayed }
        """
        result = {"clusters_found": 0, "contradictions_found": 0, "edges_decayed": 0}

        if not self.star_map:
            return result

        # 1. 发现 emergent clusters
        clusters = self._discover_clusters()
        result["clusters_found"] = len(clusters)
        self.clusters = clusters

        # 2. 检测矛盾
        contradictions = self._detect_contradictions()
        result["contradictions_found"] = len(contradictions)
        self.contradictions = contradictions

        # 3. 衰减冷边
        decayed = self._decay_cold_edges()
        result["edges_decayed"] = decayed

        # 4. ★ 调和矛盾 — 高能者留, 低能者降 ★
        resolved = self._resolve_contradictions()
        result["contradictions_resolved"] = resolved

        self.last_run = time.time()
        return result

    def _resolve_contradictions(self) -> int:
        """每个矛盾: 保留能量最高的关系, 相反关系砍半

        新结构: c["objects"] = [rel_a, rel_b]  (正反对, 如 [CAN, NOT_CAN])
        保留能量高的那个, 砍掉相反的
        """
        resolved = 0
        for c in self.contradictions:
            subj, pred_pair, rels = c["subject"], c["predicate"], list(c["objects"])
            obj = c.get("obj")  # 正反对共用同一个 obj (新检测逻辑按 subj+obj 分组)
            if obj is None:
                # 兼容: 旧结构按 pred 分组 — 直接跳过 (已由新检测替代)
                continue
            if len(rels) < 2:
                continue
            # 查正反两条边的能量
            best_rel = None
            best_energy = -1
            for rel in rels:
                e = self.star_map.conn.execute(
                    "SELECT energy FROM directed_edges WHERE source=? AND relation=? AND target=?",
                    (subj, rel, obj)).fetchone()
                energy = e[0] if e else 0
                if energy > best_energy:
                    best_energy = energy
                    best_rel = rel
            # 胜者保留, 败者砍半
            for rel in rels:
                if rel != best_rel:
                    self.star_map.conn.execute(
                        "UPDATE directed_edges SET energy=energy*0.5 "
                        "WHERE source=? AND relation=? AND target=?",
                        (subj, rel, obj))
                    resolved += 1
        if resolved:
            self.star_map.conn.commit()
        return resolved

    def _discover_clusters(self) -> dict[str, set]:
        """
        从 cognitive_traces 中发现 emergent categories.

        例如:
          猫 IS_A 哺乳动物, 狗 IS_A 哺乳动物, 海豚 IS_A 哺乳动物
          → 所有以"哺乳动物"为 obj 的 subj 形成一个聚类

        聚类键 = predicate + object (如 "IS_A::哺乳动物")
        """
        if not self.star_map or not hasattr(self.star_map, 'conn'):
            return {}

        conn = self.star_map.conn
        clusters = defaultdict(set)

        # 按 (predicate, object) 分组
        for row in conn.execute(
            "SELECT subj, pred, obj, feedback FROM cognitive_traces "
            "WHERE feedback='confirmed'"
        ):
            key = f"{row[1]}::{row[2]}"  # e.g. "IS_A::哺乳动物"
            clusters[key].add(row[0])    # add subject

        # 只保留 ≥3 个成员的聚类
        return {k: v for k, v in clusters.items() if len(v) >= 3}

    def _detect_contradictions(self) -> list[dict]:
        """
        检测矛盾: 同一 subj+obj 有正反对立的关系。

        例如:
          企鹅 CAN 飞行 (confirmed)
          企鹅 NOT_CAN 飞行 (confirmed)
          → 真矛盾, 调和

        非矛盾 (多重继承, 合法, 不调和):
          企鹅 IS_A 水鸟  +  企鹅 IS_A 鸟类  → 上下位, 都成立
          企鹅 HAS 羽毛    +  企鹅 HAS 翅膀  → 多属性, 都成立
        """
        if not self.star_map or not hasattr(self.star_map, 'conn'):
            return []

        conn = self.star_map.conn
        contradictions = []
        # 正反对: CAN↔NOT_CAN, IS_A↔NOT_IS_A, HAS↔NOT_HAS...
        OPPOSITES = {
            "CAN": "NOT_CAN", "NOT_CAN": "CAN",
            "IS_A": "NOT_IS_A", "NOT_IS_A": "IS_A",
            "HAS": "NOT_HAS", "NOT_HAS": "HAS",
            "EATS": "NOT_EATS", "NOT_EATS": "EATS",
        }
        seen = set()
        for row in conn.execute(
            "SELECT DISTINCT source, relation, target FROM directed_edges "
            "WHERE relation IN ('CAN','NOT_CAN','IS_A','NOT_IS_A','HAS','NOT_HAS','EATS','NOT_EATS')"
        ):
            subj, rel, obj = row
            opp = OPPOSITES.get(rel)
            if not opp:
                continue
            # 检查对立边是否存在
            has_opp = conn.execute(
                "SELECT 1 FROM directed_edges WHERE source=? AND relation=? AND target=? LIMIT 1",
                (subj, opp, obj)).fetchone()
            if has_opp:
                key = (subj, obj)
                if key not in seen:
                    seen.add(key)
                    contradictions.append({
                        "subject": subj,
                        "predicate": f"{rel}/{opp}",
                        "objects": [rel, opp],
                        "obj": obj,
                        "severity": "conflict"
                    })
        return contradictions

    def _decay_cold_edges(self) -> int:
        """
        衰减冷边: 长时间未被引用的共现连接, 降低 weight。

        不是删除——是让不活跃的连接在检索中自然下沉。
        """
        # co_occurrence 的 decay 已通过 _effective_weight 实现
        # 这里主要是标记——后续可扩展为主动降权
        return 0

    def get_cluster_members(self, predicate: str, obj: str) -> set:
        """查询某个聚类的成员"""
        key = f"{predicate}::{obj}"
        return self.clusters.get(key, set())

    def get_contradictions_for(self, subject: str) -> list[dict]:
        """查询某个实体的矛盾"""
        return [c for c in self.contradictions if c["subject"] == subject]
