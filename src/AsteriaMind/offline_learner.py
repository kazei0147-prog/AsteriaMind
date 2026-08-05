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
                 budget_contest=None, critic=None, concept=None):
        self.star_map = star_map
        self.active_inference = active_inference
        self.dream_module = dream_module
        self.active_learner = active_learner
        self.critic = critic
        self.concept = concept  # ★ v3.7: 概念层 (缺口想法源)
        self.budget_contest = budget_contest or BudgetContest(
            max_winners=2, monopoly_limit=3, random_explore_chance=0.10
        )
        self.last_run = 0
        self.total_runs = 0
        self.total_learned = 0
        self.history: list[dict] = []
        # ★ v3.7: 学习效果反馈 — learner_id → [胜, 总] (好奇心闭环)
        self._track: dict[str, list] = {}

    def _track_for(self, learner_id: str, default: float = 0.4) -> float:
        """历史学习效果 → track_record (样本少用默认)"""
        w, t = self._track.get(learner_id, (0, 0))
        return default if t < 3 else w / t

    def _bump_track(self, learner_id: str, won: bool):
        w, t = self._track.get(learner_id, (0, 0))
        self._track[learner_id] = [w + (1 if won else 0), t + 1]

    def run_cycle(self) -> dict:
        """
        执行一次离线学习循环。

        返回: {proposals, winners, learned, skipped}
        """
        result = {"proposals": 0, "winners": 0, "learned": 0, "skipped": 0}
        proposals = []

        # ── 1. 直接扫描星图中低置信/低权重的边 ──
        low_conf = self.star_map.conn.execute(
            "SELECT source, relation, target, confidence, energy FROM directed_edges "
            "WHERE relation IN ('IS_A','CAN','HAS','EATS','LIVES_IN') "
            "AND (confidence < 0.5 OR energy < 0.3) "
            "ORDER BY confidence ASC, energy ASC LIMIT 8").fetchall()
        for row in low_conf:
            subj, rel, obj, conf, energy = row
            proposals.append(ExplorationProposal(
                learner_id=f"scan_{subj}",
                query=f"{subj} {rel} {obj}",
                hypothesis=f"边缘不牢 (conf={conf:.1f}, energy={energy:.1f})",
                expected_value=max(0.3, 1.0 - conf),
                cost=1.0 + (1.0 - conf) * 2.0,
                uncertainty_source="low_conf",
                track_record=self._track_for(f"scan_{subj}", 0.3),
            ))

        # ── 1.5 ★ v3.6: 批判者 — 高熵实体优先学 ──
        if self.critic:
            for t in self.critic.learn_targets(top_k=5):
                proposals.append(ExplorationProposal(
                    learner_id=f"critic_{t['entity']}",
                    query=f"{t['entity']} 是什么",
                    hypothesis=f"熵态驱动 H={t['entropy']:.2f} (知识模糊)",
                    expected_value=t["entropy"],
                    cost=1.0,
                    uncertainty_source="high_entropy",
                    track_record=self._track_for(f"critic_{t['entity']}", 0.5),
                ))

        # ── 1.8 ★ v3.7: 概念层缺口 — 词表有语义位置, 星图无命名知识 ──
        if self.concept:
            try:
                named = {r[0] for r in self.star_map.conn.execute(
                    "SELECT DISTINCT source FROM directed_edges "
                    "WHERE relation IN ('IS_A','CAN','HAS','EATS','LIVES_IN')").fetchall()}
                vocab = self.concept.vocab()
                gaps = [w for w in vocab
                        if w not in named and len(w) >= 2]
                import random
                random.shuffle(gaps)
                for w in gaps[:5]:
                    proposals.append(ExplorationProposal(
                        learner_id=f"gap_{w}",
                        query=f"{w} 是什么",
                        hypothesis="概念层有语义位置, 星图无命名知识 (缺口)",
                        expected_value=0.7,
                        cost=1.2,
                        uncertainty_source="concept_gap",
                        track_record=self._track_for(f"gap_{w}", 0.4),
                    ))
            except Exception:
                pass

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
                    track_record=self._track_for(
                        f"dream_{hyp.get('strategy', 'unknown')}"),
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
                    track_record=self._track_for(f"orphan_{entity}", 0.4),
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

        # ★ v3.6: 假说自动验证 — 新知识进后检查现存假说
        if self.total_runs % 5 == 0:  # 每 5 轮做一次
            self._auto_verify_hypotheses()

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
        """执行一个学习任务: 解析 query → ActiveLearner 查询 → 存星图

        v3.7: 单实体查询 (是什么类) 用 learn_word; 三元组用 learn_relation
              学习效果反馈 → _bump_track (好奇心闭环)
        """
        if not self.active_learner:
            return False

        parts = proposal.query.split()
        subj = parts[0] if parts else ""
        if not subj or subj == "?":
            return False

        # 单实体想法 (高熵/概念缺口/孤立) → 查定义; 三元组 → 验证关系
        if proposal.uncertainty_source in ("high_entropy", "concept_gap",
                                           "orphan") or len(parts) <= 1:
            result = self.active_learner.learn_word(subj)
            learned = bool(result.get("known") and result.get("source")
                           in ("web_search", "star_map"))
        else:
            pred = parts[1] if len(parts) > 1 else "IS_A"
            obj = parts[2] if len(parts) > 2 else ""
            result = self.active_learner.learn_relation(subj, pred, obj)
            learned = bool(result.get("learned"))

        # ★ v3.7: 学习效果反馈 — 学到涨 track, 学不到降 (下次竞标更聪明)
        self._bump_track(proposal.learner_id, learned)
        if learned:
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
        # ── 假说验证率 ──
        vr = 0.0
        if self.star_map:
            total = self.star_map.conn.execute(
                "SELECT COUNT(*) FROM cognitive_traces WHERE feedback IN ('hypothesis','confirmed') "
                "AND id IN (SELECT id FROM cognitive_traces WHERE feedback='hypothesis')"
            ).fetchone()[0]
            confirmed = self.star_map.conn.execute(
                "SELECT COUNT(*) FROM cognitive_traces WHERE feedback='confirmed' "
                "AND id IN (SELECT id FROM cognitive_traces WHERE subj IS NOT NULL)"
            ).fetchone()[0]
            # 只算从 hypothesis 升级上来的 (带 "内省假说" 标记的)
            confirmed_from_hyp = self.star_map.conn.execute(
                "SELECT COUNT(*) FROM cognitive_traces WHERE feedback='confirmed' "
                "AND (pattern LIKE '%内省假说%' OR pattern LIKE '%梦境推导%')"
            ).fetchone()[0]
            hyps = self.star_map.conn.execute(
                "SELECT COUNT(*) FROM cognitive_traces WHERE feedback IN ('hypothesis','falsified') "
                "AND (pattern LIKE '%内省假说%' OR pattern LIKE '%梦境���导%')"
            ).fetchone()[0]
            # 被证实 / (被证实 + 还在等 + 被推翻)
            denom = confirmed_from_hyp + hyps
            vr = round(confirmed_from_hyp / max(denom, 1), 3) if denom > 0 else 0.0

        return {
            "total_runs": self.total_runs,
            "total_learned": self.total_learned,
            "verification_rate": vr,  # v3.6: >0.3 → 系统开始自己走路
            "last_run": self.last_run,
            "budget_contest": self.budget_contest.summary(),
            "recent_history": self.history[-5:],
        }

    def _auto_verify_hypotheses(self):
        """v3.6: 假说自动验证 — 已确认知识检验现存假说"""
        if not self.star_map: return
        cur = self.star_map.conn.cursor()
        hyps = cur.execute(
            "SELECT id, subj, pred, obj FROM cognitive_traces "
            "WHERE feedback='hypothesis'").fetchall()
        v, f = 0, 0
        for hid, subj, pred, obj in hyps:
            # 精确匹配 → 升级为 confirmed
            if cur.execute(
                "SELECT id FROM cognitive_traces WHERE subj=? AND pred=? AND obj=? "
                "AND feedback='confirmed' LIMIT 1", (subj, pred, obj)).fetchone():
                cur.execute("UPDATE cognitive_traces SET feedback='confirmed' WHERE id=?", (hid,))
                self.star_map.restore_energy(subj, obj, 0.08); v += 1
            # 矛盾 → 标记 falsified
            elif cur.execute(
                "SELECT obj FROM cognitive_traces WHERE subj=? AND pred=? "
                "AND feedback='confirmed' AND obj!=? LIMIT 1", (subj, pred, obj)).fetchone():
                cur.execute("UPDATE cognitive_traces SET feedback='falsified' WHERE id=?", (hid,))
                self.star_map.consume_energy(subj, obj, 0.1); f += 1
        if v or f:
            self.star_map.conn.commit()
            print(f"  🧪 假说验证: {v} 证实, {f} 推翻")
