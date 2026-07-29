"""
OfflineLearner — 离线学习循环 (AsteriaMind v3.3)

AM 闲时自主学习的大脑。

不是 MemoryConsolidation (整理已有知识)。
不是 DreamModule (生成假说)。
而是: 把不确定边 + 假说 + 孤立节点 → BudgetContest 竞标 → 胜者去学 → 存入星图。

职责分工:
  ActiveInference   → "什么值得学?" (找高不确定边)
  DreamModule       → "可能是什么?" (生成假说)
  BudgetContest     → "先学哪个?" (资源分配)
  ActiveLearner     → "去哪里找答案?" (执行查询)
  OfflineLearner    → 编排以上四者, 是离线循环的总调度
"""
import time
from AsteriaMind.budget_contest import BudgetContest, ExplorationProposal


class OfflineLearner:
    """
    离线学习器 — AM 的"好奇心驱动"。

    不等用户问。自己发现"我不知道什么"，自己去学。

    触发条件: 后台定时 (默认 300s), 或用户离开后空闲。
    """

    def __init__(self, star_map=None, active_inference=None,
                 dream_module=None, active_learner=None,
                 budget_contest=None):
        self.star_map = star_map
        self.active_inference = active_inference
        self.dream_module = dream_module
        self.active_learner = active_learner
        self.budget_contest = budget_contest or BudgetContest(
            max_winners=2, monopoly_limit=3, random_explore_chance=0.10
        )
        self.last_run = 0
        self.total_runs = 0
        self.total_learned = 0
        self.history: list[dict] = []

    def run_cycle(self) -> dict:
        """
        执行一次离线学习循环。

        返回: {proposals, winners, learned, skipped}
        """
        result = {"proposals": 0, "winners": 0, "learned": 0, "skipped": 0}
        proposals = []

        # ── 1. 从 ActiveInference 收集高不确定边 ──
        if self.active_inference:
            uncertain = self.active_inference.most_uncertain_edges(top_k=5)
            for edge in uncertain:
                proposals.append(ExplorationProposal(
                    learner_id=f"ai_{edge['subj']}",
                    query=f"{edge['subj']} {edge['pred']} {edge['obj']}",
                    hypothesis=f"信念不确定 (uncertainty={edge['uncertainty']:.2f})",
                    expected_value=min(1.0, edge.get("free_energy", 0.5)),
                    cost=1.0 + edge["uncertainty"] * 3.0,
                    uncertainty_source="sigma_high",
                    track_record=0.5,
                ))

        # ── 2. 从 DreamModule 收集假说 ──
        if self.dream_module:
            hypotheses = self.dream_module.dream()
            for hyp in hypotheses[:5]:
                proposals.append(ExplorationProposal(
                    learner_id=f"dream_{hyp.get('strategy', 'unknown')}",
                    query=f"{hyp['subject']} {hyp['predicate']} {hyp.get('object', '')}",
                    hypothesis=hyp.get("reasoning", "梦境假说"),
                    expected_value=hyp.get("confidence", 0.2),
                    cost=0.5,
                    uncertainty_source="structure_gap",
                    track_record=self._strategy_track_record(hyp.get("strategy")),
                ))

        # ── 3. 从星图找孤立节点 ──
        if self.star_map:
            orphans = self._find_orphan_entities(top_k=3)
            for entity, edge_count in orphans:
                proposals.append(ExplorationProposal(
                    learner_id=f"orphan_{entity}",
                    query=f"{entity} IS_A ?",
                    hypothesis=f"孤立节点 (只有{edge_count}条边), 需要补全关系",
                    expected_value=0.6,
                    cost=0.8,
                    uncertainty_source="structure_gap",
                    track_record=0.4,
                ))

        result["proposals"] = len(proposals)
        if not proposals:
            return result

        # ── 4. BudgetContest 竞标 ──
        winners = self.budget_contest.evaluate(proposals)
        result["winners"] = len(winners)

        # ── 5. 胜者去学 ──
        for winner in winners:
            learned = self._execute_learning(winner)
            if learned:
                result["learned"] += 1
                self.total_learned += 1
            else:
                result["skipped"] += 1
                # ★ v3.5: 内省写入 — 学不到的把假说存为 HYPOTHESIS 边
                self._store_hypothesis(winner)

        self.total_runs += 1
        self.last_run = time.time()

        self.history.append({
            "run": self.total_runs,
            "timestamp": self.last_run,
            "proposals": len(proposals),
            "winners": len(winners),
            "learned": result["learned"],
        })
        if len(self.history) > 20:
            self.history = self.history[-20:]

        return result

    def _execute_learning(self, proposal: ExplorationProposal) -> bool:
        """执行一个学习任务: 解析 query → ActiveLearner 查询 → 存星图"""
        if not self.active_learner:
            return False

        # 从 query 解析三元组
        parts = proposal.query.split()
        subj = parts[0] if parts else ""
        pred = parts[1] if len(parts) > 1 else "IS_A"
        obj = parts[2] if len(parts) > 2 else ""

        if not subj or subj == "?":
            return False

        result = self.active_learner.learn_relation(subj, pred, obj)

        if result.get("learned"):
            if self.active_inference:
                self.active_inference.update_from_feedback(subj, pred, obj, True)
            return True

        return False

    def _store_hypothesis(self, proposal: ExplorationProposal):
        """
        v3.6: 假说质量过滤 — Novelty × Evidence × Confidence, merge dupes

        Score = Novelty (0-1) × Evidence (0-1) × BaseConfidence - Cost
        重复已存在 → merge, 不新建。
        已确认 → 跳过。
        """
        if not self.star_map:
            return
        parts = proposal.query.split()
        subj = parts[0] if parts else ""
        pred = parts[1] if len(parts) > 1 else "IS_A"
        obj = parts[2] if len(parts) > 2 else ""
        if not subj or not pred or not obj:
            return
        if subj in ("?", "未知", "") or obj in ("?", "未知", ""):
            return  # 太模糊

        # ── 1. Novelty Check ──
        existing = self.star_map.conn.execute(
            "SELECT id, feedback FROM cognitive_traces "
            "WHERE subj=? AND pred=? AND obj=? LIMIT 1",
            (subj, pred, obj)).fetchone()

        if existing:
            if existing[1] == "confirmed":
                return
            if existing[1] == "hypothesis":
                # 重复假说 → 仅记录, 不新建 (confidence 非 schema 列)
                return

        # ── 2. Evidence Check ──
        # 假说是否有同方向的有向边支撑?
        evidence = 0.3  # 基线: 梦境本身是弱证据
        for row in self.star_map.conn.execute(
            "SELECT COUNT(*) FROM directed_edges WHERE source=? AND target=?",
            (subj, obj)):
            if row[0] > 0:
                evidence += 0.15  # 有向边支撑
        neg_evidence = self.star_map.conn.execute(
            "SELECT COUNT(*) FROM directed_edges "
            "WHERE (source=? AND target=?) AND relation LIKE 'NOT_%'",
            (subj, obj)).fetchone()[0]
        if neg_evidence > 0:
            evidence -= 0.4  # 存在矛盾证据 → 低分

        # ── 3. Quality Score ──
        cost = 0.1
        score = 0.5 * evidence * 0.25 - cost  # Novelty×Evidence×Confidence - Cost
        if score <= 0:
            return  # 质量太低, 不存

        # 存为 tentative hypothesis
        self.star_map.store(
            subj, pred, obj, "hypothesis",
            f"内省假说(s={score:.2f}): {proposal.hypothesis if hasattr(proposal,'hypothesis') else '梦境推导'}"
        )

    def _find_orphan_entities(self, top_k=5) -> list[tuple[str, int]]:
        """找孤立实体: 在认知痕迹中出现但边很少的"""
        if not self.star_map or not hasattr(self.star_map, 'conn'):
            return []

        conn = self.star_map.conn
        entity_edges = {}
        for row in conn.execute(
            "SELECT subj, obj FROM cognitive_traces WHERE feedback='confirmed'"
        ):
            for entity in (row[0], row[1]):
                if entity:
                    entity_edges[entity] = entity_edges.get(entity, 0) + 1

        sorted_entities = sorted(entity_edges.items(), key=lambda x: x[1])
        return [(e, c) for e, c in sorted_entities[:top_k] if c <= 2]

    def _strategy_track_record(self, strategy: str) -> float:
        """从 DreamModule 的策略统计获取历史准确率"""
        if not self.dream_module:
            return 0.3
        s = self.dream_module.strategies.get(strategy, {})
        generated = s.get("generated", 0)
        accepted = s.get("accepted", 0)
        if generated == 0:
            return s.get("base_confidence", 0.2)
        return accepted / max(generated, 1)

    def summary(self) -> dict:
        return {
            "total_runs": self.total_runs,
            "total_learned": self.total_learned,
            "last_run": self.last_run,
            "budget_contest": self.budget_contest.summary(),
            "recent_history": self.history[-5:],
        }
