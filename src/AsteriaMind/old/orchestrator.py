"""
调度器 - HiveMind 2.9 主循环

v2.9 重构:
- 四层自主探索管道: CuriosityEngine → Learner.drive() → BudgetContest → MotherMind fallback
- CuriosityEngine 不再直接触发搜索，而是触发"注意信号"
- Learner 自己决定是否探索，BudgetContest 分配资源
- 母模块作为 fallback: 当 Learner 没有有效提案时，自己发起探索
"""
import random
import time
import logging
from typing import List, Optional
from .learner import Learner
from .trust import TrustEngine
from .mother import MotherMind, Decision
from .guard import StabilityGuard
from .portal import Portal, Emission, CuriosityEngine
from .budget_contest import BudgetContest, ExplorationProposal

logger = logging.getLogger("AsteriaMind.orchestrator")


PRESET_PERSONAS = [
    {"name": "L1_optimist",    "mu": +3.0, "sigma": 8.0,  "window": 5,  "hint": "天生乐观"},
    {"name": "L2_pessimist",   "mu": -3.0, "sigma": 8.0,  "window": 5,  "hint": "天生悲观"},
    {"name": "L3_skeptic",     "mu":  0.0, "sigma": 15.0, "window": 10, "hint": "高度不确定，爱怀疑"},
    {"name": "L4_stubborn",    "mu":  0.0, "sigma": 3.0,  "window": 3,  "hint": "很自信，学得慢"},
    {"name": "L5_adaptable",   "mu":  0.0, "sigma": 10.0, "window": 12, "hint": "灵活，窗口大"},
]


class HiveMindV2:
    """HiveMind 2.3 — 母模块是决策者，子模块是大脑"""

    def __init__(
        self,
        n_learners: int = 5,
        warmup_rounds: int = 50,
        propose_interval: int = 5,
        debate_rounds: int = 2,
        verify_ratio: float = 0.1,
        use_personas: bool = True,
    ):
        if use_personas:
            self.learners = [
                Learner(name=p["name"], window_size=p["window"],
                        initial_mu=p["mu"], initial_sigma=p["sigma"])
                for p in PRESET_PERSONAS[:n_learners]
            ]
        else:
            self.learners = [Learner(name=f"L{i+1}") for i in range(n_learners)]

        # ── v2.3: 母模块升级 ──
        self.mother = MotherMind(debate_rounds=debate_rounds)

        # ── v2.3: Guard 只做架构保护 ──
        self.guard = StabilityGuard()

        self.trust = TrustEngine()
        for l in self.learners:
            self.trust.register(l.learner_id)

        self.warmup_rounds = warmup_rounds
        self.propose_interval = propose_interval
        self.verify_ratio = verify_ratio

        self.round_num = 0
        self.data_buffer: List[float] = []
        self.verify_buffer: List[float] = []
        self.consensus_history: List[float] = []
        self.log: List[dict] = []
        self.decisions: List[Decision] = []
        self.contest = BudgetContest()        # v2.9: 群体治理

    def run(self, datasource, max_rounds: int = 500) -> dict:
        """完整运行流程"""
        # Phase 1: 预热
        logger.info(f"预热期: {self.warmup_rounds} 轮")
        for _ in range(self.warmup_rounds):
            val = self._fetch(datasource)
            if val is None: break
            for learner in self.learners:
                learner.observe(val)
            self.round_num += 1

        # Phase 2: 运行
        logger.info(f"运行期开始, 最大 {max_rounds} 轮")
        for _ in range(max_rounds):
            val = self._fetch(datasource)
            if val is None: break
            self.round_num += 1

            for learner in self.learners:
                learner.observe(val)

            # 定期讨论
            if self.round_num % self.propose_interval == 0:
                self._discussion_round(val)

            # 事后验证
            if len(self.verify_buffer) >= 5:
                self._verify()
                self.verify_buffer = []

            if random.random() < self.verify_ratio:
                self.verify_buffer.append(val)

        return self._final_summary()

    def run_continuous(
        self,
        portal: Portal,
        max_rounds: int = 0,
        poll_interval: float = 0.1,
    ):
        """
        v2.4: 持续运行模式 — 好奇心驱动数据拉取。

        系统不是等待被喂数据，而是主动判断:
        - "我够不够确定？要不要拉新数据来看看？"
        - "Learner 是不是太不确定了？需要更多信息？"
        - "太久没新数据了，该去检查一下了？"

        参数:
        - portal: 统一的 I/O 入口
        - max_rounds: 最大讨论轮数 (0 = 无限)
        - poll_interval: 基础轮询间隔（秒）
        """
        logger.info(f"持续运行模式启动 — {len(self.learners)} 个 Learner, "
                    f"预热 {self.warmup_rounds} 轮")

        # Phase 1: 预热
        warmup_count = 0
        while warmup_count < self.warmup_rounds and portal.source.has_more():
            val = portal.poll()
            if val is None:
                if not portal.source.has_more():
                    break
                time.sleep(poll_interval)
                continue
            for learner in self.learners:
                learner.observe(val)
            self.round_num += 1
            warmup_count += 1

        portal.emit_status(f"预热完成 ({self.warmup_rounds} 轮)，进入持续运行")

        # Phase 2: 持续运行
        last_confidence = 1.0
        discussions = 0

        while portal.running:
            # ── 好奇心决定是否拉数据 ──
            should, reason = portal.curiosity.should_poll(
                last_confidence,
                self.learners,
                portal.seconds_since_last_data(),
            )

            # v2.9: "search" → 四层自主探索管道
            if should == "search":
                portal.emit_alert(f"Curiosity: {reason}")
                self._autonomous_exploration(portal)
                continue

            if should:
                val = portal.poll()
                if val is None:
                    if not portal.source.has_more():
                        portal.emit_status("数据源已耗尽，等待中...")
                        time.sleep(poll_interval)
                        continue
                else:
                    self.round_num += 1
                    for learner in self.learners:
                        learner.observe(val)

                    # 定期讨论
                    if self.round_num % self.propose_interval == 0:
                        log_entry = self._discussion_round(val)
                        last_confidence = log_entry.get("confidence", 1.0)

                        # 通过 Portal 发射决策
                        if self.decisions:
                            portal.emit_decision(self.decisions[-1])

                        discussions += 1
                        if max_rounds > 0 and discussions >= max_rounds:
                            portal.emit_status(f"达到最大讨论轮数 ({max_rounds})，停止")
                            break

                    # 验证
                    if len(self.verify_buffer) >= 5:
                        self._verify()
                        self.verify_buffer = []
                    if random.random() < self.verify_ratio:
                        self.verify_buffer.append(val)

            # 无论是否拉数据，保持 Learner 自由思考
            # (Learner 可以在没有新数据时基于内部窗口继续推演)

            time.sleep(poll_interval)

        portal.emit_status(f"持续运行结束 — {discussions} 次讨论")
        return self._final_summary()

    # ──────────── v2.9: 四层自主探索管道 ────────────

    def _autonomous_exploration(self, portal: Portal):
        """
        四层管道:
          1. CuriosityEngine → 检测到 knowledge_gap / structure_gap
          2. Learner exploration_drive() → 生成 proposals
          3. BudgetContest → 竞标，分配资源
          4. MotherMind fallback → 没有有效提案时，系统级探索

        返回: 是否有探索被执行
        """
        # Layer 1: 每个 Learner 产生探索欲
        proposals = []
        for l in self.learners:
            drive = l.exploration_drive()
            if drive:
                proposals.append(ExplorationProposal(
                    learner_id=l.learner_id,
                    query=drive["query"],
                    hypothesis=drive["hypothesis"],
                    expected_value=drive["value"],
                    cost=drive["cost"],
                    uncertainty_source=drive["source"],
                    track_record=l.track_record(),
                ))

        # Layer 2+3: 竞标
        if proposals:
            winners = self.contest.evaluate(proposals)
            for w in winners:
                portal.emit_search(w.query)
                logger.info(
                    f"探索: [{w.learner_id}] '{w.query[:50]}' "
                    f"(value={w.expected_value:.2f}, source={w.uncertainty_source})"
                )
            return True

        # Layer 4: 母级 fallback — 没人提，MotherMind 自己探索
        query = self.mother.formulate_query(self.learners)
        portal.emit_search(f"[系统探索] {query}")
        logger.info(f"母级探索: '{query}'")
        return True

    def _discussion_round(self, current_obs: float) -> dict:
        """
        v2.3 重构: 母模块主持讨论

        旧: chains → evaluator.full_discussion() → 数字
        新: chains → mother.deliberate() → 有推理的决策
        """
        # 各 Learner 提案
        chains = []
        for learner in self.learners:
            chain = learner.propose(current_obs)
            chains.append(chain)

        # ── v2.3: 母模块深思熟虑 ──
        decision = self.mother.deliberate(
            self.learners, chains, self.trust, current_obs
        )
        self.decisions.append(decision)
        self.consensus_history.append(decision.consensus)

        # ── Guard 检查 (只保护架构，不抑制思考) ──
        guard_result = self.guard.check(
            self.learners, self.trust,
            decision.consensus,
            abs(decision.consensus - current_obs),
        )
        # Guard 的干预只用于记录，不影响决策流程
        if guard_result.get("violations"):
            logger.warning(f"架构违规: {guard_result['violations']}")

        return {
            "round": self.round_num,
            "consensus": decision.consensus,
            "confidence": decision.confidence,
            "reasoning": decision.reasoning,
            "primary_influence": decision.primary_influence,
            "dissenting_view": decision.dissenting_view,
            "reservations": decision.reservations,
            "feedback": {
                lid: fb
                for lid, fb in decision.learner_feedback.items()
            },
            "trust_ranking": [
                f"{lid}:{t:.2f}"
                for lid, t in (self.trust.rank() if hasattr(self.trust, 'rank') else [])[:3]
            ],
            "guard": guard_result.get("status", "stable"),
        }

    def _verify(self):
        """事后验证: 更新信念 + 信任"""
        if not self.verify_buffer:
            return
        true_value = sum(self.verify_buffer) / len(self.verify_buffer)
        for learner in self.learners:
            if learner.history:
                learner.learn(true_value, learner.history[-1])
                self.trust.verify(learner.learner_id, learner.history[-1], true_value)

    def _fetch(self, datasource) -> Optional[float]:
        val = datasource.fetch()
        if val is not None:
            self.data_buffer.append(val)
        return val

    def _final_summary(self) -> dict:
        learners_summary = []
        for l in self.learners:
            learners_summary.append({
                "id": l.learner_id,
                "mu": l.belief.mu,
                "sigma": l.belief.sigma,
                "alpha": l.belief.alpha,
                "track_record": l.track_record(),
                "avg_error": l.average_error(),
                "trust": self.trust.get(l.learner_id),
                "total_rounds": l.total_rounds,
            })

        return {
            "version": "2.3.0-alpha",
            "total_rounds": self.round_num,
            "n_learners": len(self.learners),
            "warmup_rounds": self.warmup_rounds,
            "n_discussions": len(self.log),
            "n_decisions": self.mother.decision_count,
            "final_consensus": (
                self.consensus_history[-1] if self.consensus_history else None
            ),
            "mother_summary": self.mother.summary(),
            "learners": learners_summary,
            "trust_summary": self.trust.summary(),
        }

    # ── 梦境接口 (保持向后兼容) ──
    def save_dream(self, filepath: str):
        from .dream import DreamStore
        store = DreamStore()
        return store.save(self.learners, filepath)

    @classmethod
    def from_dream(cls, filepath: str, **kwargs) -> "HiveMindV2":
        from .dream import DreamStore
        store = DreamStore()
        states = store.load(filepath)
        instance = cls(use_personas=False, n_learners=0)
        instance.learners = DreamStore.restore_learners(states)
        for l in instance.learners:
            instance.trust.register(l.learner_id)
        instance.warmup_rounds = 0
        return instance
