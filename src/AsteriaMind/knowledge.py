"""
Knowledge Core — AsteriaMind 的脑内世界 (v3.0)

核心理念:
  不是存一堆"苹果 是 水果"的死数据。
  而是: 每个关系有自己的 Bayesian 信念(alpha/beta),
       有反证据记录、有时间戳、有上下文标签。
       系统可以追问"你多确定?"、"什么时候验证的?"、
       "什么情况下不对?"、"你最近是越来越确信还是越来越动摇?"

三个基本元素:
  Entity   — 概念: "线性函数", "y=2x+5", "导数"
  Relation — 带贝叶斯信念的有向关系
  Evidence — 支持/反证据链 (每条关系有自己的证据谱)

核心操作:
  observe_support()   — "又看到了一次, 更确定了"
  observe_counter()   — "等等, 这次不是这样, 在 X 语境下它是 Y"
  query()             — "y=2x+5 的导数是什么?"
  growth_trend()      — "这条知识最近是稳定了还是在动摇?"
  detect_staleness()  — "这条知识上次验证是 3 天前, 该复查了"
"""
import time
from dataclasses import dataclass, field
from typing import List, Optional, Tuple


@dataclass
class CounterEvidence:
    """一条反证据: 在什么语境下, 这条关系不成立"""
    alternative: str              # 替代解释
    context: str = ""             # 语境描述
    weight: float = 0.5           # 这条反证据的分量
    timestamp: float = 0.0

    def __post_init__(self):
        if self.timestamp == 0.0:
            self.timestamp = time.time()


@dataclass
class Belief:
    """
    用 Beta(α, β) 表示一个信念。

    α = 支持证据的累积分
    β = 反对证据的累积分

    置信度 = α / (α+β)     (Beta 分布均值)
    不确定性 = α·β / ((α+β)² · (α+β+1))  (Beta 方差)
    """
    alpha: float = 1.0
    beta: float = 1.0

    @property
    def confidence(self) -> float:
        total = self.alpha + self.beta
        return self.alpha / total if total > 0 else 0.5

    @property
    def evidence_total(self) -> float:
        return self.alpha + self.beta

    @property
    def uncertainty(self) -> float:
        total = self.alpha + self.beta
        if total <= 1:
            return 0.25
        return (self.alpha * self.beta) / (total * total * (total + 1))

    @property
    def is_strong(self) -> bool:
        return self.confidence > 0.85 and self.evidence_total > 5

    @property
    def is_contested(self) -> bool:
        return self.beta > 0 and self.beta > self.alpha * 0.2

    def observe_support(self, weight: float = 1.0):
        self.alpha += weight

    def observe_against(self, weight: float = 0.5):
        self.beta += weight

    def summary(self) -> str:
        pct = self.confidence * 100
        if self.is_strong:
            return f"稳固 ({pct:.0f}%, 证据 {self.evidence_total:.0f} 条)"
        elif self.is_contested:
            return f"动摇 ({pct:.0f}%, 反证据 {self.beta:.1f} 条)"
        else:
            return f"待验证 ({pct:.0f}%)"


@dataclass
class Relation:
    """
    一条知识: subject --[predicate]--> object

    不是死数据, 是活的 Bayesian 信念:
      - belief: 贝叶斯信念 (alpha/beta)
      - counter_evidence: 什么情况下这条关系不成立
      - first_observed / last_verified: 时间戳 (检测陈旧)
      - source: 从哪里来的
    """
    subject: str
    predicate: str
    object: str
    belief: Belief = field(default_factory=Belief)
    counter_evidence: List[CounterEvidence] = field(default_factory=list)
    first_observed: float = 0.0
    last_verified: float = 0.0
    source: str = "observed"

    def __post_init__(self):
        if self.first_observed == 0.0:
            self.first_observed = time.time()
        if self.last_verified == 0.0:
            self.last_verified = self.first_observed

    @property
    def confidence(self) -> float:
        return self.belief.confidence

    @property
    def uncertainty(self) -> float:
        return self.belief.uncertainty

    @property
    def is_stale(self) -> bool:
        """超过 24 小时未验证 → 陈旧"""
        return (time.time() - self.last_verified) > 86400

    def key(self) -> str:
        return f"{self.subject}--[{self.predicate}]-->{self.object}"

    def growth_trend(self) -> str:
        """
        成长趋势:
          "consolidated"  — 证据充分, 无人质疑
          "stable"        — 持续观察, 稳定
          "contested"     — 有反证据, 信念在摇摆
          "uncertain"     — 证据太少, 不确定
          "stale"         — 太久没验证
        """
        if self.is_stale:
            return "stale"
        if self.belief.is_strong:
            return "consolidated"
        if self.belief.is_contested:
            return "contested"
        if self.belief.evidence_total > 3:
            return "stable"
        return "uncertain"

    def observe(self, correct: bool, weight: float = 1.0,
                context: str = "", alternative: str = ""):
        """
        观察到一次验证:
          correct=True  → 增加 α (更自信)
          correct=False → 增加 β + 记录反证据语境
        """
        if correct:
            self.belief.observe_support(weight)
        else:
            self.belief.observe_against(weight)
            if alternative or context:
                self.counter_evidence.append(CounterEvidence(
                    alternative=alternative,
                    context=context,
                    weight=weight,
                ))
        self.last_verified = time.time()


# ═══════════════════ 知识图谱 ═══════════════════

class KnowledgeGraph:
    """AsteriaMind 的脑内世界——带多键索引 + SQLite 持久化"""

    def __init__(self, db_path: str = None):
        self.relations: list[Relation] = []
        # 多键索引: (subject, predicate) → [Relation]
        self._sp_index: dict[str, list[Relation]] = {}
        # 主键索引: "subj--[pred]-->obj" → Relation
        self._key_index: dict[str, Relation] = {}
        # 可扩展假说注册表
        self.hypothesis_extensions: list[dict] = []
        # 持久化路径
        self.db_path = db_path
        if db_path:
            self._init_db()

    def register_hypothesis_template(self, template: dict):
        """
        注册一个新的假说生成模板。

        元假说层调用此方法来扩展假说框架本身。
        模板格式: {id, label, mechanism, condition_fn, generate_fn, complexity}
        """
        self.hypothesis_extensions.append(template)

    # ── 写入 ──

    def add(self, subject: str, predicate: str, object: str,
            confidence: float = 0.5, source: str = "observed") -> Relation:
        """O(1) 索引写入——不再扫描全表"""
        key = f"{subject}--[{predicate}]-->{object}"
        alpha = max(0.1, confidence * 10)
        beta = max(0.1, (1 - confidence) * 10)

        # O(1) 主键查重
        if key in self._key_index:
            rel = self._key_index[key]
            rel.belief.alpha += alpha
            rel.belief.beta = max(0.1, (rel.belief.beta + beta) / 2)
            rel.last_verified = time.time()
            self._persist_rel(rel)
            return rel

        rel = Relation(
            subject=subject, predicate=predicate, object=object,
            belief=Belief(alpha=alpha, beta=beta), source=source,
        )
        self.relations.append(rel)
        self._key_index[key] = rel
        spk = f"{subject}::{predicate}"
        self._sp_index.setdefault(spk, []).append(rel)
        self._persist_rel(rel)
        return rel

    def observe(self, subject: str, predicate: str, object: str,
                correct: bool = True, weight: float = 0.5,
                context: str = "", alternative: str = "") -> Relation:
        """更新 α/β: 支持证据加 α, 反证据加 β 并记录 counter_evidence"""
        key = f"{subject}--[{predicate}]-->{object}"
        rel = self._key_index.get(key)

        if rel is None:
            rel = self.add(subject, predicate, object,
                           confidence=0.3, source="observed")

        if correct:
            rel.belief.alpha += weight
        else:
            rel.belief.beta += weight
            if context or alternative:
                rel.counter_evidence.append({
                    "context": context, "alternative": alternative, "time": time.time(),
                })

        rel.last_verified = time.time()
        self._persist_rel(rel)
        return rel

    # ── 持久化 ──

    def _init_db(self):
        if not self.db_path:
            return
        self._conn = __import__('sqlite3').connect(self.db_path)
        self._conn.execute('''CREATE TABLE IF NOT EXISTS relations (
            key TEXT PRIMARY KEY, subject TEXT, predicate TEXT, object TEXT,
            alpha REAL, beta REAL, source TEXT,
            counter_evidence TEXT, last_verified REAL
        )''')
        self._conn.commit()
        self._load_from_db()

    def _persist_rel(self, rel: Relation):
        if not hasattr(self, '_conn'):
            return
        import json
        self._conn.execute('''INSERT OR REPLACE INTO relations VALUES (?,?,?,?,?,?,?,?,?)''',
                           (rel.key(), rel.subject, rel.predicate, rel.object,
                            rel.belief.alpha, rel.belief.beta, rel.source,
                            json.dumps(rel.counter_evidence, ensure_ascii=False),
                            rel.last_verified))
        self._conn.commit()

    def _load_from_db(self):
        import json
        rows = self._conn.execute('SELECT * FROM relations').fetchall()
        for row in rows:
            key, subj, pred, obj, alpha, beta, source, ce_json, lv = row
            rel = Relation(
                subject=subj, predicate=pred, object=obj,
                belief=Belief(alpha=alpha, beta=beta),
                source=source, last_verified=lv or time.time(),
            )
            try:
                rel.counter_evidence = json.loads(ce_json) if ce_json else []
            except Exception:
                rel.counter_evidence = []
            self.relations.append(rel)
            self._key_index[key] = rel
            spk = f"{subj}::{pred}"
            self._sp_index.setdefault(spk, []).append(rel)

    def save(self, filepath: str = None):
        """保存到 JSON 文件"""
        path = filepath or "asteriamind_kg.json"
        import json
        data = [{
            "key": r.key(), "subject": r.subject, "predicate": r.predicate,
            "object": r.object, "alpha": r.belief.alpha, "beta": r.belief.beta,
            "confidence": r.confidence, "source": r.source,
            "counter_evidence": [
                ce if isinstance(ce, dict) else {"context": ce.context,
                    "alternative": ce.alternative, "time": ce.timestamp}
                for ce in r.counter_evidence
            ],
            "last_verified": r.last_verified,
        } for r in self.relations]
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    @classmethod
    def load(cls, filepath: str) -> 'KnowledgeGraph':
        """从 JSON 文件加载"""
        import json
        kg = cls()
        with open(filepath, 'r', encoding='utf-8') as f:
            data = json.load(f)
        for d in data:
            rel = kg.add(d["subject"], d["predicate"], d["object"],
                         confidence=d.get("confidence", 0.5),
                         source=d.get("source", "loaded"))
            rel.belief.alpha = d.get("alpha", rel.belief.alpha)
            rel.belief.beta = d.get("beta", rel.belief.beta)
            rel.counter_evidence = d.get("counter_evidence", [])
        return kg

    def learn_from(self, relations: list[tuple]):
        """批量学习"""
        for item in relations:
            if len(item) == 4:
                self.add(*item)
            else:
                self.add(*item[:3])

    # ── 验证 ──

    def observe(self, subject: str, predicate: str, object: str,
                correct: bool, weight: float = 1.0,
                context: str = "", alternative: str = "") -> Optional[Relation]:
        """用一次观察更新一条关系的信念"""
        for r in self.relations:
            if r.subject == subject and r.predicate == predicate and r.object == object:
                r.observe(correct, weight, context, alternative)
                return r
        return None

    # ── 自主思考 (v3.0) ──

    def generate_goals(self, max_goals: int = 3) -> list[dict]:
        """
        从知识图谱本身生成探索目标——不需要外部告诉她要查什么。

        三种自带的目标类型:
          gap — 实体连接太少, 需要更多关系
          conflict — 同一 subject-predicate 有多个 object, 矛盾
          uncertain — 置信度最低的关系, 需要验证
        """
        goals = []

        # 1. 知识缺口
        all_entities = set()
        for r in self.relations:
            all_entities.add(r.subject)
            all_entities.add(r.object)
        for e in all_entities:
            n = sum(1 for r in self.relations if r.subject == e or r.object == e)
            if n <= 1:
                goals.append({
                    "type": "gap",
                    "target": e,
                    "reason": f"对\"{e}\"了解太少 (仅 {n} 条关系)",
                    "priority": 1.0 / max(n, 1),
                })

        # 2. 矛盾
        for (s, p), rels in self._group_by_sp().items():
            objs = set(r.object for r in rels)
            if len(objs) > 1:
                goals.append({
                    "type": "conflict",
                    "target": f"{s}--[{p}]",
                    "reason": f"\"{s}\"的\"{p}\"有多个答案: {objs}",
                    "priority": 0.9,
                })

        # 3. 最不确定
        for r in self.most_uncertain(3):
            if r.confidence < 0.6:
                goals.append({
                    "type": "uncertain",
                    "target": r.key(),
                    "reason": f"置信度仅 {r.confidence:.2f}, 需要验证",
                    "priority": 1.0 - r.confidence,
                })

        goals.sort(key=lambda g: -g["priority"])
        return goals[:max_goals]

    def generate_competing_hypotheses(self, target: str, target_type: str = "gap") -> list[dict]:
        """
        多假说竞争: 对同一个结构现象, 生成多个互斥的解释。

        H1: 结构相似 → 缺失的边应该存在 (类比推理)
        H2: 共同原因 → target 和相似实体被同一个上级节点驱动
        H3: 表面相似 → 只是巧合, 没有深层联系
        H4: 间接路径 → 存在未观察到的中间节点

        每个假说附带: 可观察预测、验证方式、置信度
        """
        hypos = []

        if target_type == "gap":
            target_entity = target
        elif "--[" in target:
            target_entity = target.split("--[")[0].strip()
        else:
            target_entity = target

        sigs = self._build_signatures()
        target_sig = sigs.get(target_entity, set())
        existing_preds = set(p for p, _ in target_sig)

        # ── H1: 类比推理 (结构相似 → 缺失边应存在) ──
        analogies = self._find_analogies(target_entity, sigs, existing_preds)
        if analogies:
            best = analogies[0]
            hypos.append({
                "id": "H1",
                "label": f"类比: {target_entity} 可能也 {best['predicate']} {best['counterpart']}",
                "mechanism": "结构相似性",
                "detail": f"与\"{best['source_entity']}\"相似度 {best['similarity']:.2f}",
                "confidence": round(best["similarity"] * 0.4, 3),
                "prediction": f"如果 H1 正确, 应观察到: {target_entity} {best['predicate']} {best['counterpart']} 这种情况频繁出现",
                "test": "多次观察",  # default test method
                "discrimination": f"区别于 H2: H1 预测 {target_entity} 主动影响 {best['counterpart']}, H2 预测它们都是被动结果",
                "complexity": {"free_params": 1, "assumptions": 1, "base_cost": 0.0},
            })

        # ── H2: 共同原因 (共享邻居 → 被同一个上级驱动) ──
        common_causes = self._find_common_causes(target_entity, sigs)
        if common_causes:
            cc = common_causes[0]
            hypos.append({
                "id": "H2",
                "label": f"共同原因: {cc['cause']} 同时导致了 {target_entity} 和 {cc['associated']}",
                "mechanism": "共因混淆",
                "detail": f"两者都连接到 {cc['cause']} (共 {cc['shared_count']} 个共享节点)",
                "confidence": round(len(cc["shared"]) / max(1, len(target_sig)) * 0.35, 3),
                "prediction": f"如果 H2 正确, 应观察到: 移除 {cc['cause']} 后, {target_entity} 和 {cc['associated']} 不再相关",
                "test": "条件独立",
                "discrimination": f"区别于 H1: H2 认为相关性来自共同父节点, 而非 {target_entity} 自身的属性",
                "complexity": {"free_params": 1, "assumptions": 2, "base_cost": 0.05},
            })

        # ── H3: 表面相似 (低置信度 → 巧合) ──
        hypos.append({
            "id": "H3",
            "label": f"巧合: {target_entity} 的相似性只是噪音",
            "mechanism": "统计偶然",
            "detail": f"当前证据不足以建立任何因果或类比关系",
            "confidence": 0.1,
            "prediction": f"如果 H3 正确, 应观察到: {target_entity} 与其他实体的关系没有规律, 增加数据后相似度下降而非上升",
            "test": "增加样本量",
            "discrimination": "区别于 H1/H2: H3 预测持续增加数据不会让关系变强",
            "complexity": {"free_params": 0, "assumptions": 0, "base_cost": 0.0},
        })

        # ── H4: 间接路径 (缺失的中间节点) ──
        indirect = self._find_indirect_paths(target_entity, sigs)
        if indirect:
            ip = indirect[0]
            hypos.append({
                "id": "H4",
                "label": f"间接路径: {target_entity} 通过 {ip['mid']} 间接连接到 {ip['target']}",
                "mechanism": "中介效应",
                "detail": f"存在路径 {target_entity} → ? → {ip['target']}",
                "confidence": round(ip["strength"] * 0.3, 3),
                "prediction": f"如果 H4 正确, 应观察到: {target_entity} 影响 {ip['mid']}, {ip['mid']} 再影响 {ip['target']}, 而非直接连接",
                "test": "中介分析",
                "discrimination": f"区别于 H1: H4 预测关系是间接的, 控制 {ip['mid']} 后直接效应消失",
                "complexity": {"free_params": 2, "assumptions": 2, "base_cost": 0.10},
            })

        result = sorted(hypos, key=lambda h: -h["confidence"])

        # ── H6: 隐藏条件 — 两方都有可能对 ──
        h6 = self._detect_hidden_condition(target_entity, sigs)
        if h6:
            result.append(h6)

        # ── H5: 元假说 ──
        coverage = sum(h["confidence"] for h in result[:3])
        if coverage < 0.6:
            residual = 1.0 - coverage
            novel_pattern = self._analyze_residual(target_entity, sigs, residual)
            h5 = {
                "id": "H5",
                "label": f"未知机制: {novel_pattern['description']}",
                "mechanism": "未建模模式",
                "detail": f"现有 H1-H4 仅解释 {coverage*100:.0f}%, 剩余 {residual*100:.0f}% 变异来自未知来源",
                "confidence": round(residual * 0.5, 3),
                "prediction": f"如果 H5 正确, 应观察到: {novel_pattern['describe_pattern']}",
                "test": "探索性分析",
                "discrimination": "区别于 H1-H4: 需要一个现有框架无法描述的新机制",
                "meta": True,
                "complexity": {
                    "free_params": novel_pattern.get("param_count", 2),
                    "assumptions": novel_pattern.get("assumption_count", 3),
                    "base_cost": 0.15,  # 未知机制的固有复杂性惩罚
                },
            }
            result.append(h5)

        # ── 可扩展假说: 元假说注册的自定义类型 ──
        for ext in self.hypothesis_extensions:
            try:
                condition = ext.get("condition_fn")
                generate = ext.get("generate_fn")
                if condition and generate and condition(self, target_entity, sigs):
                    h_custom = generate(self, target_entity, sigs)
                    h_custom["id"] = ext["id"]
                    h_custom["mechanism"] = ext.get("mechanism", "扩展")
                    h_custom["complexity"] = ext.get("complexity",
                        {"free_params": 1, "assumptions": 1, "base_cost": 0.05})
                    result.append(h_custom)
            except Exception:
                pass

        # ── 奥卡姆剃刀: 重新打分, 惩罚复杂假说 ──
        result = self._apply_occam(result)
        return result

    def _detect_hidden_condition(self, entity, sigs) -> dict:
        """
        H6: 检测"隐藏条件"模式。

        当图谱中存在 X PRED P Y 和 X NOT_P Y 两个互为否定的主张,
        且两者都有非零置信度时, 不一定是"一个对一个错"。
        可能是: "两者在不同条件下都对"。

        例如: "运动 CAUSES 体重下降" vs "运动 NOT_CAUSES 体重下降"
              → 隐藏条件: 饮食控制、运动类型、时间尺度。
        """
        for r in self.relations:
            if r.predicate.startswith("NOT_") and r.confidence > 0.05:
                base_pred = r.predicate[4:]
                # 找对立主张
                opposites = [r2 for r2 in self.relations
                             if r2.subject == r.subject
                             and r2.predicate == base_pred
                             and r2.object == r.object
                             and r2.confidence > 0.1]
                if opposites:
                    opp = opposites[0]
                    # 两者都有一定置信度 → 隐藏条件假说
                    both_credible = min(r.confidence, opp.confidence) > 0.05
                    if both_credible:
                        return {
                            "id": "H6",
                            "label": f"隐藏条件: {r.subject} 可能在特定条件下 {base_pred} {r.object}, 其他条件下则不",
                            "mechanism": "条件依赖",
                            "detail": f"两方都有证据: {base_pred}({opp.confidence:.2f}) vs NOT_{base_pred}({r.confidence:.2f})",
                            "confidence": round(min(0.4, (r.confidence + opp.confidence) / 2), 3),
                            "prediction": f"如果 H6 正确, 应观察到: 控制某个未观测变量后, 矛盾消失——两者分别在不同条件下成立",
                            "test": "条件对照实验",
                            "discrimination": f"区别于 H1/H2: H6 认为冲突是表面的, 真正的问题是缺少条件变量",
                            "complexity": {"free_params": 1, "assumptions": 2, "base_cost": 0.05},
                        }
        return None

    def _apply_occam(self, hypotheses: list[dict]) -> list[dict]:
        """
        奥卡姆剃刀评分:
          Score = 置信度 + 证据匹配 - α·自由参数 - β·假设数 - 固有代价

        目的: 防止"上帝变量"假说每次都赢。
        越复杂的假说需要越强的证据才能胜出。
        """
        ALPHA = 0.10   # 每个自由参数的惩罚
        BETA = 0.08    # 每个假设的惩罚

        for h in hypotheses:
            cx = h.get("complexity", {})
            params = cx.get("free_params", 0)
            assumptions = cx.get("assumptions", 0)
            base = cx.get("base_cost", 0)

            evidence = h.get("confidence", 0)
            occam_score = evidence - ALPHA * params - BETA * assumptions - base
            h["occam_score"] = round(max(0.0, occam_score), 3)
            h["complexity_breakdown"] = f"参数×{params} 假设×{assumptions} 固有:{base:.2f}"

        return sorted(hypotheses, key=lambda h: -h["occam_score"])

    def _analyze_residual(self, entity, sigs, residual) -> dict:
        """
        分析未解释的残差, 提取可能的模式。
        这是"发现第四种机制"的核心——不是从固定类型选, 而是从数据残差中推断新类型。
        """
        target_sig = sigs.get(entity, set())
        incoming = sum(1 for p, _ in target_sig if p.startswith("←"))
        outgoing = len(target_sig) - incoming

        if incoming == 0 and outgoing == 0:
            return {
                "description": f"{entity} 与图谱完全孤立, 可能属于一个未建模的子图",
                "describe_pattern": f"{entity} 连接到当前图谱之外的新区域",
            }
        elif incoming > outgoing * 2:
            return {
                "description": f"{entity} 主要是被动方 (入度 {incoming} >> 出度 {outgoing}), 可能受未观测的全局因素影响",
                "describe_pattern": f"{entity} 的行为由外部隐变量驱动, 而非图内关系",
            }
        elif outgoing > incoming * 2:
            return {
                "description": f"{entity} 主要是主动方 (出度 {outgoing} >> 入度 {incoming}), 可能是一个未观测的因果源",
                "describe_pattern": f"{entity} 可能是未建模的底层原因, 通过未知路径影响图中其他节点",
            }
        else:
            return {
                "description": f"{entity} 的残差没有明显的结构特征, 需要更多数据来辨识新机制",
                "describe_pattern": f"增加多样化数据以揭示当前框架无法捕捉的模式",
            }

        return sorted(result, key=lambda h: -h["confidence"])

    def _find_analogies(self, entity, sigs, existing_preds, n=3) -> list[dict]:
        results = []
        target_sig = sigs.get(entity, set())
        for other, other_sig in sigs.items():
            if other == entity:
                continue
            shared = target_sig & other_sig
            total = target_sig | other_sig
            if not total:
                continue
            sim = len(shared) / len(total)
            novel = set(p for p, _ in other_sig) - existing_preds
            for pred in novel:
                cps = [cp for p, cp in other_sig if p == pred]
                for cp in cps:
                    results.append({
                        "source_entity": other, "predicate": pred,
                        "counterpart": cp, "similarity": sim,
                    })
        return sorted(results, key=lambda r: -r["similarity"])[:n]

    def _find_common_causes(self, entity, sigs) -> list[dict]:
        """找共享的邻居节点 (共同原因)"""
        incoming_target = set(cp for p, cp in sigs.get(entity, set()) if p.startswith("←"))
        results = []
        for other, other_sig in sigs.items():
            if other == entity:
                continue
            incoming_other = set(cp for p, cp in other_sig if p.startswith("←"))
            shared = incoming_target & incoming_other
            if len(shared) >= 1:
                results.append({
                    "cause": list(shared)[0],
                    "associated": other,
                    "shared": list(shared),
                    "shared_count": len(shared),
                })
        return sorted(results, key=lambda r: -r["shared_count"])

    def _find_indirect_paths(self, entity, sigs, max_hops=2) -> list[dict]:
        """找两跳以内的间接路径"""
        results = []
        outgoing = [(p, cp) for p, cp in sigs.get(entity, set()) if not p.startswith("←")]
        for pred, mid in outgoing:
            mid_outgoing = [(p, cp) for p, cp in sigs.get(mid, set()) if not p.startswith("←")]
            for mp, target in mid_outgoing:
                if target != entity:
                    # bidirectional tie strength
                    strength = 1.0 / max(max_hops, 1)
                    results.append({
                        "mid": mid, "target": target,
                        "path": f"{entity}→{mid}→{target}",
                        "strength": strength,
                    })
        return sorted(results, key=lambda r: -r["strength"])
        """
        基于图拓扑相似性生成假说——不预设任何 predicate 白名单。

        原理:
          1. 找图谱中与 target 结构相似的实体
          2. 相似实体有的关系, target 没有 → 假说: target 可能也有
          3. 假说由相似度 + 源关系置信度 + 不确定性共同加权

        这是"图谱嵌入 + 信念传播"的最简实现。
        """
        hypotheses = []
        target_entity = target.split("--[")[0].strip() if "--[" in target else target

        # 如果目标是实体名, 直接找类比
        if target_type == "gap":
            search_entity = target_entity
        else:
            search_entity = target_entity

        # ── 图拓扑相似性 ──
        entity_signatures = self._build_signatures()
        target_sig = entity_signatures.get(search_entity, set())

        if not target_sig:
            return self._fallback_hypotheses(target, target_type)

        existing_predicates = set(p for p, _ in target_sig)

        similarities = []
        for other_entity, other_sig in entity_signatures.items():
            if other_entity == search_entity:
                continue
            # Jaccard: shared signature tuples / total
            shared = target_sig & other_sig
            total = target_sig | other_sig
            if not total:
                continue
            sim = len(shared) / len(total)
            if sim > 0:
                # 对方有但 target 没有的 predicate
                novel = set(p for p, _ in other_sig) - existing_predicates
                for pred in novel:
                    # 找到该 predicate 在对方中的 counterpart
                    counterparts = [cp for p, cp in other_sig if p == pred]
                    for cp in counterparts:
                        similarities.append({
                            "source_entity": other_entity,
                            "predicate": pred,
                            "counterpart": cp,
                            "similarity": sim,
                            "source_confidence": 0.5,
                        })

        similarities.sort(key=lambda s: -s["similarity"])

        for s in similarities[:5]:
            statement = f"{search_entity} 可能也 {s['predicate']} {s['counterpart']}"
            based_on = (f"与\"{s['source_entity']}\"结构相似度 {s['similarity']:.2f}, "
                       f"它有 {s['predicate']} 关系")
            conf = s["similarity"] * 0.4  # 图相似驱动的置信度
            hypotheses.append({
                "statement": statement,
                "based_on": based_on,
                "confidence": round(conf, 3),
                "source": "graph_topology",
            })

        if not hypotheses:
            return self._fallback_hypotheses(target, target_type)
        return hypotheses

    def _build_signatures(self) -> dict:
        """
        建立实体签名: {entity_name: set of (predicate, counterpart)} 元组。

        不是 predicate → Relation 的一对一映射,
        而是 predicate + 对方实体的组合, 区分"被A拥有的X"和"被B拥有的X"。
        """
        sigs: dict[str, set] = {}
        for r in self.relations:
            # subject 的签名: 包含 (predicate, object)
            sigs.setdefault(r.subject, set()).add((r.predicate, r.object))
            # object 的签名: 包含 (incoming_predicate, subject)
            sigs.setdefault(r.object, set()).add((f"←{r.predicate}", r.subject))
        return sigs

    def _fallback_hypotheses(self, target: str, target_type: str) -> list[dict]:
        """当图拓扑无法产生假说时的兜底 (仅用于空图)"""
        return [{
            "statement": f"需要更多关于\"{target}\"的数据",
            "based_on": "图谱信息不足以产生有意义的假说",
            "confidence": 0.1,
            "source": "fallback",
        }]

    def explain_change(self, key: str, before_conf: float, after_conf: float,
                       before_alpha: float, after_alpha: float,
                       before_beta: float, after_beta: float) -> str:
        """
        用图谱自身的关系结构解释为什么信念变了。
        不是模板——是基于图谱中的 pattern 做归因。
        """
        parts = key.split("--[")
        if len(parts) < 2:
            return "无法解析关系"

        delta = after_conf - before_conf
        alpha_delta = after_alpha - before_alpha
        beta_delta = after_beta - before_beta

        # 从图谱中找到可能的归因
        subject = parts[0].strip()
        predicate = parts[1].split("]-->")[0].strip() if "]-->" in parts[1] else ""
        obj = parts[1].split("]-->")[1].strip() if "]-->" in parts[1] else ""

        reasons = []

        if alpha_delta > 0.5:
            # 看看是否有支持性关系帮助了增长
            supporters = [r for r in self.relations
                          if (r.subject == subject or r.object == subject)
                          and r.confidence > 0.7 and r.key() != key]
            if supporters:
                reasons.append(f"已有 {len(supporters)} 条高置信度相关关系提供了间接支持")

        if beta_delta > 0.5:
            # 看看是否有矛盾关系导致下降
            contradictors = [r for r in self.relations
                             if r.subject == subject and r.predicate == predicate
                             and r.object != obj]
            if contradictors:
                alt_objects = [r.object for r in contradictors]
                reasons.append(f"存在矛盾: 同一关系指向了 {alt_objects}")

        if not reasons:
            if abs(delta) < 0.02:
                return f"信念变化很小 ({delta:+.3f})，现有证据不足以改变判断。需要更多数据。"
            if delta > 0:
                return f"信念增强了 ({delta:+.3f})，新证据与现有知识一致。"
            else:
                return f"信念削弱了 ({delta:+.3f})，新证据挑战了现有认知。"

        return "；".join(reasons)

    # ── 内部辅助 ──

    def _group_by_sp(self) -> dict:
        groups = {}
        for r in self.relations:
            key = (r.subject, r.predicate)
            groups.setdefault(key, []).append(r)
        return groups

    # ── 查询 ──

    def query(self, subject: str, predicate: str = None) -> list[Relation]:
        """O(1) 索引查询: 先按 (subject, predicate) 查, 补充 object 匹配"""
        results = []
        # 按 subject 精确索引
        if predicate:
            spk = f"{subject}::{predicate}"
            if spk in self._sp_index:
                results = list(self._sp_index[spk])
        # 按 key 前缀扫描 (O(n) 但 n 是索引键数, 比全表小得多)
        if not results:
            prefix = f"{subject}--["
            for key, rel in self._key_index.items():
                if key.startswith(prefix) and (predicate is None or f"--[{predicate}]-->" in key):
                    results.append(rel)
        # 补充: subject 作为 object 出现的关系
        for key, rel in self._key_index.items():
            if key.endswith(f"]-->{subject}") and (predicate is None):
                if rel not in results:
                    results.append(rel)
        return sorted(results, key=lambda r: -r.confidence)

    def ask(self, question: str) -> Optional[dict]:
        """自然语言查询, 返回 {'answer', 'confidence', 'trend', 'n_counter'}"""
        parts = question.replace("的", " ").replace("是什么", "").strip().split()
        if len(parts) >= 2:
            results = self.query(parts[0], parts[1])
            if results:
                best = results[0]
                return {
                    "answer": best.object,
                    "confidence": round(best.confidence, 3),
                    "trend": best.growth_trend(),
                    "evidence": f"α={best.belief.alpha:.1f} β={best.belief.beta:.1f}",
                    "n_counter": len(best.counter_evidence),
                    "verified_ago": f"{(time.time()-best.last_verified)/3600:.1f}h",
                }
        return None

    # ── 推理 ──

    def infer(self) -> list[Relation]:
        """传递推理 A→B 且 B→C → A→C"""
        new_relations = []
        for r1 in self.relations:
            for r2 in self.relations:
                if r1.object == r2.subject and r1.predicate == r2.predicate:
                    combined_alpha = min(r1.belief.alpha, r2.belief.alpha) * 0.8
                    combined_beta = max(r1.belief.beta, r2.belief.beta) * 1.2
                    inferred = Relation(
                        subject=r1.subject, predicate=r1.predicate, object=r2.object,
                        belief=Belief(alpha=combined_alpha, beta=combined_beta),
                        source="inferred",
                    )
                    if not any(n.subject == inferred.subject
                               and n.predicate == inferred.predicate
                               and n.object == inferred.object
                               for n in self.relations + new_relations):
                        new_relations.append(inferred)
        self.relations.extend(new_relations)
        for nr in new_relations:
            self._index.setdefault(nr.subject, []).append(nr)
        return new_relations

    # ── 诊断 ──

    def detect_gaps(self, min_relations: int = 2) -> list[str]:
        gaps = []
        entities = set()
        for r in self.relations:
            entities.add(r.subject)
            entities.add(r.object)
        for e in entities:
            n = sum(1 for r in self.relations if r.subject == e or r.object == e)
            if n < min_relations:
                gaps.append(f"{e} (仅 {n} 条关系)")
        return gaps

    def detect_conflicts(self) -> list[Tuple[Relation, Relation]]:
        """同一 subject-predicate 有多个不同 object → 矛盾"""
        conflicts = []
        seen: dict[tuple, Relation] = {}
        for r in self.relations:
            key = (r.subject, r.predicate)
            if key in seen:
                if seen[key].object != r.object:
                    conflicts.append((seen[key], r))
            else:
                seen[key] = r
        return conflicts

    def detect_staleness(self, max_hours: float = 24) -> list[Relation]:
        """太久没验证的知识"""
        now = time.time()
        return [r for r in self.relations
                if (now - r.last_verified) > max_hours * 3600]

    def most_uncertain(self, n: int = 5) -> list[Relation]:
        return sorted(self.relations, key=lambda r: r.confidence)[:n]

    def growth_report(self) -> list[dict]:
        """每条关系的成长状态"""
        return [{
            "key": r.key(),
            "confidence": round(r.confidence, 3),
            "alpha": round(r.belief.alpha, 1),
            "beta": round(r.belief.beta, 1),
            "trend": r.growth_trend(),
            "n_counter": len(r.counter_evidence),
            "is_stale": r.is_stale,
        } for r in self.relations]

    # ── 导出 ──

    def summary(self) -> dict:
        entities = len(set(r.subject for r in self.relations) | set(r.object for r in self.relations))
        consolidated = sum(1 for r in self.relations if r.growth_trend() == "consolidated")
        contested = sum(1 for r in self.relations if r.growth_trend() == "contested")
        stale = sum(1 for r in self.relations if r.is_stale)
        return {
            "entities": entities,
            "relations": len(self.relations),
            "consolidated": consolidated,
            "contested": contested,
            "stale": stale,
            "avg_confidence": round(
                sum(r.confidence for r in self.relations) / max(1, len(self.relations)), 3),
        }

    def dump(self) -> str:
        lines = []
        for r in sorted(self.relations, key=lambda x: -x.confidence):
            bar = "█" * int(r.confidence * 10) + "░" * (10 - int(r.confidence * 10))
            trend = {"consolidated": "🟢", "stable": "🔵", "contested": "🟡",
                     "uncertain": "⚪", "stale": "⏳"}.get(r.growth_trend(), "?")
            ce = f" 反证×{len(r.counter_evidence)}" if r.counter_evidence else ""
            lines.append(
                f"  {trend} {r.subject:20s} --[{r.predicate:15s}]--> {r.object:20s}  "
                f"[{bar}] {r.confidence:.2f}  {r.belief.summary()}{ce}"
            )
        return "\n".join(lines)
