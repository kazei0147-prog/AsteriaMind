"""
CrossLayerBridge + QueryRouter — 符号层与语义层的桥梁 (AsteriaMind v3.2)

不是再加一层。
是让现有的两层(精确符号 + 向量语义)之间产生结构性对话。

三层能力:
  1. AutoClustering: 向量空间 → 隐式类别 → 映射回符号层
  2. DirectionVector: 发现关系方向相似性 → 推断机制类比
  3. QueryRouter: 查询自动路由 (精确 vs 语义 vs 混合)
"""
import math, time
from dataclasses import dataclass, field
from typing import List, Tuple, Optional, Dict
from collections import defaultdict


@dataclass
class ImplicitCategory:
    """从向量空间自动发现的隐式类别——不需要人定义"""
    id: str
    members: List[str]       # 属于这个类别的知识 key
    centroid: List[float]    # 类别中心向量
    coherence: float         # 类内聚集度
    label_hint: str = ""     # 从符号层推断的标签 (如 "提神类物质")
    discovered_at: float = field(default_factory=time.time)


@dataclass
class DirectionPattern:
    """向量空间中发现的关系方向模式"""
    source_category: str      # 源知识群
    target_direction: List[float]  # 方向向量
    similar_relations: List[str]   # 共享这个方向的关系
    coherence: float               # 方向一致性
    insight: str = ""              # 推断: "这些实体可能共享作用机制"


class CrossLayerBridge:
    """
    符号↔向量 跨层桥梁。

    不是被动存储——主动发现向量空间中的结构, 映射回符号层。
    """

    def __init__(self, kg=None, vector_layer=None):
        self.kg = kg
        self.vl = vector_layer
        self.categories: List[ImplicitCategory] = []
        self.directions: List[DirectionPattern] = []
        self.last_cluster_time = 0.0
        self.cluster_interval = 100  # 每 100 步或 100 条新知识触发一次

    def discover(self) -> dict:
        """
        跨层发现: 聚类 + 方向 + 映射。

        返回:
          {clusters: [...], directions: [...], cross_mappings: [...]}
        """
        if not self.vl or len(self.vl.relations) < 3:
            return {"clusters": [], "directions": [], "cross_mappings": []}

        clusters = self._auto_cluster()
        directions = self._find_directions()
        mappings = self._map_to_symbolic(clusters, directions)

        self.categories.extend(clusters)
        self.directions.extend(directions)
        self.last_cluster_time = time.time()

        return {"clusters": clusters, "directions": directions, "cross_mappings": mappings}

    def _auto_cluster(self, n_clusters: int = None) -> List[ImplicitCategory]:
        """
        简易 K-means 风格聚类: 在向量空间中找语义群组。

        自动决定簇数: n_clusters = min(sqrt(N), 20)
        """
        vectors = [vr.vector for vr in self.vl.relations]
        keys = [vr.relation_key for vr in self.vl.relations]
        N = len(vectors)
        if N < 3:
            return []

        k = n_clusters or min(max(2, int(math.sqrt(N))), 20)

        # 初始化中心: 随机选 k 个点
        import random as _r
        _r.seed(42)
        indices = _r.sample(range(N), min(k, N))
        centroids = [vectors[i][:] for i in indices]

        # Lloyd 迭代
        for _ in range(10):
            assignments = [[] for _ in range(k)]
            for i, v in enumerate(vectors):
                best_c = max(range(k), key=lambda c: self.vl._cosine(v, centroids[c]))
                assignments[best_c].append(i)

            new_centroids = []
            for c_idx in range(k):
                if assignments[c_idx]:
                    avg = [0.0] * len(centroids[0])
                    for i in assignments[c_idx]:
                        for j, val in enumerate(vectors[i]):
                            avg[j] += val
                    n = len(assignments[c_idx])
                    avg = [v / n for v in avg]
                    new_centroids.append(avg)
                else:
                    new_centroids.append(centroids[c_idx])
            centroids = new_centroids

        # 生成类别
        categories = []
        for c_idx in range(k):
            if not assignments[c_idx]:
                continue
            member_keys = [keys[i] for i in assignments[c_idx]]
            coherence = self._cluster_coherence(
                [vectors[i] for i in assignments[c_idx]], centroids[c_idx])

            # 从符号层推断标签
            label = self._infer_label(member_keys)

            categories.append(ImplicitCategory(
                id=f"cluster_{len(self.categories)+c_idx+1}",
                members=member_keys,
                centroid=centroids[c_idx],
                coherence=coherence,
                label_hint=label,
            ))

        return sorted(categories, key=lambda c: -c.coherence)

    def _find_directions(self) -> List[DirectionPattern]:
        """
        方向向量: 找共享相似 (subject → object) 方向的关系模式。

        如果 "咖啡→清醒" 和 "茶→清醒" 的向量方向接近,
        推断它们的 subject 可能共享作用机制。
        """
        patterns = []

        # 按 predicate 分组
        by_pred: Dict[str, List[Tuple[int, List[float]]]] = defaultdict(list)
        for i, vr in enumerate(self.vl.relations):
            by_pred[vr.predicate].append((i, vr.vector))

        for pred, entries in by_pred.items():
            if len(entries) < 2:
                continue

            # 对每对同一 predicate 的关系, 计算方向相似度
            pairs = []
            for i in range(len(entries)):
                for j in range(i + 1, len(entries)):
                    idx_a, vec_a = entries[i]
                    idx_b, vec_b = entries[j]
                    sim = self.vl._cosine(vec_a, vec_b)
                    if sim > 0.5:
                        pairs.append((self.vl.relations[idx_a].relation_key,
                                      self.vl.relations[idx_b].relation_key, sim))

            if pairs:
                avg_sim = sum(p[2] for p in pairs) / len(pairs)
                insight = self._infer_direction_insight(pairs, pred)
                patterns.append(DirectionPattern(
                    source_category=pred,
                    target_direction=entries[0][1],
                    similar_relations=[p[0] for p in pairs] + [p[1] for p in pairs],
                    coherence=avg_sim,
                    insight=insight,
                ))

        return sorted(patterns, key=lambda d: -d.coherence)

    def _map_to_symbolic(self, clusters, directions) -> List[dict]:
        """
        将向量空间发现映射回符号层。

        对每个聚类, 在 KG 中创建隐式类别关系。
        对每个方向模式, 生成机制类比假说。
        """
        mappings = []

        for cluster in clusters[:5]:
            if cluster.coherence < 0.3:
                continue
            label = cluster.label_hint or f"语义群组_{cluster.id}"
            # 在 KG 中注册这个隐式类别
            for member in cluster.members[:10]:
                if self.kg:
                    self.kg.add(member, "BELONGS_TO_CLUSTER", label,
                                confidence=cluster.coherence * 0.5,
                                source="cross_layer_bridge")
            mappings.append({
                "type": "cluster_mapped",
                "cluster": label,
                "members": len(cluster.members),
                "coherence": round(cluster.coherence, 3),
            })

        for direction in directions[:3]:
            if direction.coherence < 0.5:
                continue
            # 为方向相似的 relation pairs 在 KG 中建立关联
            keys = list(set(direction.similar_relations))
            for i in range(len(keys)):
                for j in range(i + 1, len(keys)):
                    if self.kg:
                        self.kg.add(keys[i], "SIMILAR_DIRECTION_AS", keys[j],
                                    confidence=direction.coherence * 0.4,
                                    source="cross_layer_bridge")
            mappings.append({
                "type": "direction_mapped",
                "insight": direction.insight,
                "relations": len(keys),
                "coherence": round(direction.coherence, 3),
            })

        return mappings

    def _cluster_coherence(self, vectors, centroid) -> float:
        """类内平均余弦相似度"""
        if len(vectors) < 2:
            return 1.0
        sims = [self.vl._cosine(v, centroid) for v in vectors]
        return sum(sims) / len(sims)

    def _infer_label(self, member_keys: List[str]) -> str:
        """从符号层推断聚类的语义标签 (简化为高频 subject/predicate)"""
        subjects = []
        for key in member_keys:
            parts = key.split("--[")
            if parts:
                subjects.append(parts[0].strip())
        if not subjects:
            return ""
        # 最常见的前两个 subject
        from collections import Counter
        top = Counter(subjects).most_common(2)
        return " · ".join(s for s, _ in top)

    def _infer_direction_insight(self, pairs, predicate) -> str:
        """从方向相似性推断机制"""
        return (f"多个实体共享 '{predicate}' 关系的方向模式, "
                f"推断它们可能存在类似的因果/作用机制")


class QueryRouter:
    """
    查询路由: 自动决定应该走哪一层。

    精确层: 结构化查询 ("X CAUSES 什么?")
    语义层: 模糊查询 ("什么东西提神?")
    混合层: 精确没匹配时自动降级到语义
    桥接层: 查询触发了向量结构发现
    """

    STRUCTURED_PATTERNS = [
        "CAUSES", "IS_A", "HAS", "PREDICTS", "INCREASES", "DECREASES",
        "CORRELATED", "TRIGGERS", "DEPENDS_ON", "RESPONDS_TO",
    ]

    def __init__(self, kg=None, vl=None, bridge: CrossLayerBridge = None):
        self.kg = kg
        self.vl = vl
        self.bridge = bridge
        self.route_log: list[dict] = []

    def route(self, query: str) -> dict:
        """
        自动路由查询。

        返回 {layer, results, fallback_used, bridge_insight}
        """
        decision = self._decide(query)

        if decision == "exact" and self.kg:
            results = self._exact_query(query)
            if results:
                self.route_log.append({"query": query, "layer": "exact", "hits": len(results)})
                return {"layer": "exact", "results": results, "fallback_used": False}

        # 精确无结果 → 降级到语义
        if decision in ("semantic", "exact") and self.vl:
            sem_results = self.vl.search(query, top_k=5)
            self.route_log.append({"query": query, "layer": "semantic",
                                   "hits": len(sem_results), "fallback": decision == "exact"})

            # 如果桥接层存在且语义结果足够 → 触发跨层发现
            bridge_insight = None
            if self.bridge and len(sem_results) >= 2:
                discovery = self.bridge.discover()
                if discovery["cross_mappings"]:
                    bridge_insight = discovery["cross_mappings"][:2]

            return {"layer": "semantic", "results": sem_results,
                    "fallback_used": decision == "exact",
                    "bridge_insight": bridge_insight}

        return {"layer": "none", "results": [], "fallback_used": False,
                "reason": "no_matching_layer"}

    def _decide(self, query: str) -> str:
        """判断查询类型"""
        query_upper = query.upper()
        for pattern in self.STRUCTURED_PATTERNS:
            if pattern in query_upper:
                return "exact"
        # 自然语言提问
        if any(kw in query for kw in ["什么", "哪个", "谁", "怎么", "为什么", "如何"]):
            return "semantic"
        return "exact"  # 默认精确

    def _exact_query(self, query: str) -> list:
        """精确层查询"""
        parts = query.split()
        if len(parts) >= 2:
            subj = parts[0]
            for pat in self.STRUCTURED_PATTERNS:
                if pat in query.upper():
                    return self.kg.query(subj, pat)
            return self.kg.query(subj)
        return []
