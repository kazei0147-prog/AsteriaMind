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

    def __init__(self, star_map=None, critic=None, concept=None):
        self.star_map = star_map
        self.critic = critic          # ID-024③ 锚2: 批判者熵
        self.concept = concept        # ID-024③ 锚4: 双向判读 (ID-018)
        self.clusters: dict[str, set] = {}       # cluster_id → {entities}
        self.cluster_centroids: dict[str, str] = {}  # cluster_id → central entity
        self.contradictions: list[dict] = []       # [(subj, pred, obj_a, obj_b), ...]
        self.last_run: float = 0
        self._dual_a_consistency: float | None = None  # 锚4 全局缓存 (一次 consolidation 只算一次)

    def consolidate(self) -> dict:
        """
        执行一次完整的记忆巩固循环。

        返回: { clusters_found, contradictions_found, edges_decayed, promoted_to_a, growth }
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

        # 5. ★ v3.9 ID-024③: B→A 升级 — 四锚外部验证 (不可自指) ★
        promoted = self._promote_to_tier_a()
        result["promoted_to_a"] = promoted

        # 6. ★ v3.9 ID-024④: 增长模型 W(t) — 边数/tier 分布快照 (S 型实证数据) ★
        result["growth"] = self._growth_snapshot()

        self.last_run = time.time()
        return result

    # ── ID-024③: B→A 四锚升级 (A 层准入只认外部锚, 不可自指) ──
    def _promote_to_tier_a(self) -> int:
        """B 层边 → A 层: 四锚 OR (任一满足即升级)

        锚1 用户 confirmed ≥ 3 次 (cognitive_traces 计数)
        锚2 批判者熵 < 0.5 (该实体知识结构清晰)
        锚3 黑盒 co_text 共现支持 (energy ≥ 0.3)
        锚4 双向判读方向A 一致率 ≥ 0.7 (ID-018, 全局黑盒贴合度)

        闸门自己打的分不算数 — 四锚全部来自外部 (用户/熵/黑盒/双向判读)
        """
        if not self.star_map or not hasattr(self.star_map, "conn"):
            return 0
        conn = self.star_map.conn
        promoted = 0
        rows = conn.execute(
            "SELECT source, relation, target FROM directed_edges "
            "WHERE tier='B' AND relation != 'co_text'").fetchall()
        if not rows:
            return 0

        # 锚4 全局一致率只算一次
        if self._dual_a_consistency is None:
            self._dual_a_consistency = self._anchor4_global()
        a4 = self._dual_a_consistency

        for subj, rel, obj in rows:
            if self._check_anchors(subj, rel, obj, a4):
                conn.execute(
                    "UPDATE directed_edges SET tier='A' "
                    "WHERE source=? AND relation=? AND target=?",
                    (subj, rel, obj))
                promoted += 1
        if promoted:
            conn.commit()
        return promoted

    def _anchor4_global(self) -> float | None:
        """锚4: 双向判读方向A 一致率 (ID-018) — 无 concept 时跳过"""
        if not self.concept or not hasattr(self.concept, "dual_check"):
            return None
        try:
            dual = self.concept.dual_check(sample=6)
            return dual["direction_a_whitebox_to_blackbox"]["consistency"]
        except Exception:
            return None

    def _check_anchors(self, subj: str, rel: str, obj: str,
                       a4: float | None) -> bool:
        """四锚 OR — 任一满足即通过 (各自独立阈值)"""
        conn = self.star_map.conn
        # 锚1: 用户 confirmed ≥ 3 次
        n_conf = conn.execute(
            "SELECT COUNT(*) FROM cognitive_traces "
            "WHERE subj=? AND pred=? AND obj=? AND feedback='confirmed'",
            (subj, rel, obj)).fetchone()[0]
        if n_conf >= 3:
            return True
        # 锚2: 批判者熵 < 0.5 (该实体知识结构清晰)
        if self.critic and hasattr(self.critic, "entropy_of"):
            try:
                if self.critic.entropy_of(subj) < 0.5:
                    return True
            except Exception:
                pass
        # 锚3: 黑盒 co_text 共现支持 (energy ≥ 0.3)
        co = conn.execute(
            "SELECT energy FROM directed_edges "
            "WHERE source=? AND target=? AND relation='co_text'",
            (subj, obj)).fetchone()
        if co and (co[0] or 0) >= 0.3:
            return True
        # 锚4: 双向判读方向A 一致率 ≥ 0.7
        if a4 is not None and a4 >= 0.7:
            return True
        return False

    # ── ID-024④: 增长模型 W(t) 快照 (S 型实证数据) ──
    def _growth_snapshot(self) -> dict:
        """W(t) = 命名边总数 + tier 分布 — 供 S 型曲线实证 (带宽/候选池/噪声/饱和)"""
        if not self.star_map or not hasattr(self.star_map, "conn"):
            return {}
        conn = self.star_map.conn
        try:
            total = conn.execute(
                "SELECT COUNT(*) FROM directed_edges WHERE relation != 'co_text'").fetchone()[0]
            tier_a = conn.execute(
                "SELECT COUNT(*) FROM directed_edges WHERE tier='A'").fetchone()[0]
            tier_b = conn.execute(
                "SELECT COUNT(*) FROM directed_edges WHERE tier='B'").fetchone()[0]
            return {"W": total, "tier_a": tier_a, "tier_b": tier_b}
        except Exception:
            return {}

    def _resolve_contradictions(self) -> int:
        """每个矛盾: 保留证据强度高的关系, 相反关系降权

        ★ v3.6: 证据强度 = weight × confidence × energy
          (不再是裸 energy — w=33 的真知识不该输给 w=1 的错知识)

        ★ v3.6: 深度保护 — 降权有下限, 不砍到趋近 0
          loser.energy = max(loser.energy*0.5, 0.2 * winner_weight)
          → 确认 33 次的知识最低降到 0.2×33=6.6, 永远压过 w=1 的
        """
        resolved = 0
        for c in self.contradictions:
            subj, pred_pair, rels = c["subject"], c["predicate"], list(c["objects"])
            obj = c.get("obj")  # 正反对共用同一个 obj
            if obj is None or len(rels) < 2:
                continue
            # 查正反两条边的证据强度 (weight × confidence × energy)
            best_rel = None
            best_strength = -1.0
            winner_weight = 1
            for rel in rels:
                e = self.star_map.conn.execute(
                    "SELECT energy, weight, confidence FROM directed_edges "
                    "WHERE source=? AND relation=? AND target=?",
                    (subj, rel, obj)).fetchone()
                if not e:
                    continue
                energy, weight, conf = e
                strength = (weight or 1) * (conf or 0.5) * (energy or 0.5)
                if strength > best_strength:
                    best_strength = strength
                    best_rel = rel
                    winner_weight = weight or 1
            if best_rel is None:
                continue
            # 败者降权, 有下限 (深度保护: 按败者自己的证据深度)
            # loser.energy = max(loser.energy*0.5, 0.2*loser.weight)
            # → w=33 的知识最多降到 6.6, 不会被 w=1 的压死
            # → 降权只降不升 (max 不会把低能量拉高)
            for rel in rels:
                if rel != best_rel:
                    loser = self.star_map.conn.execute(
                        "SELECT energy, weight, tier FROM directed_edges "
                        "WHERE source=? AND relation=? AND target=?",
                        (subj, rel, obj)).fetchone()
                    if not loser:
                        continue
                    loser_energy, loser_weight, loser_tier = loser
                    floor = 0.2 * (loser_weight or 1)
                    self.star_map.conn.execute(
                        "UPDATE directed_edges SET energy=MAX(energy*0.5, ?), "
                        "tier=CASE WHEN tier='A' THEN 'B' ELSE tier END "
                        "WHERE source=? AND relation=? AND target=?",
                        (floor, subj, rel, obj))
                    # ★ v3.9 ID-024③: A→B 降级 — A 层非终身制, 被反证调和即降级
                    if loser_tier == "A":
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
