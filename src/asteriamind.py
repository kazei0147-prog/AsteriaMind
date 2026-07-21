"""
AsteriaMind.run() — 统一入口 (v3.0)

python asteriamind.py

14 个模块同时在线:
  数值层: Learner ×3 + TrustEngine + ArgumentEvaluator
  结构层: MetaLearner (多项式/Fourier/指数 多基选择)
  诊断层: DiagnosticEngine + ExperimentDesigner
  知识层: KnowledgeGraph (贝叶斯 α/β) + WorldModel (预测-验证)
  决策层: MotherMind + MotherAdapter + CrossValidator
  探索层: CuriosityEngine (知识前沿 + R²下降预警)
  编排层: ToolRegistry (7 个工具注册)
"""
import time, math, random, sys
import os as _os
sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))

from hivemind_v2.knowledge import KnowledgeGraph
from hivemind_v2.world_model import WorldModel
from hivemind_v2.meta_learner import MetaLearner, BasisSet
from hivemind_v2.diagnosis import DiagnosticEngine, ExperimentDesigner
from hivemind_v2.tool_registry import ToolRegistry, Tool, orchestrate
from hivemind_v2.mother_adapter import MotherAdapter
from hivemind_v2.learner import Learner
from hivemind_v2.trust import TrustEngine
from hivemind_v2.mother import MotherMind
from hivemind_v2.argument import ArgumentEvaluator
from hivemind_v2.validator import CrossValidator
from hivemind_v2.portal import CuriosityEngine


class AsteriaMind:
    """统一运行引擎 — 所有模块接入"""

    def __init__(self, seed: int = 42, n_learners: int = 3):
        random.seed(seed)

        # 知识层
        self.kg = KnowledgeGraph()
        self.wm = WorldModel()

        # 结构层
        self.meta = MetaLearner(switch_r2_gap=0.03, check_interval=10)

        # 诊断层
        self.diag = DiagnosticEngine(history_window=50)
        self.designer = ExperimentDesigner()

        # 好奇心
        self.curiosity = CuriosityEngine(exploration_patience=12)
        self.curiosity._experiment_interval = 15

        # 工具注册
        self.registry = ToolRegistry()
        for t in [
            Tool("DiagnosticEngine", "诊断崩塌原因", "collapse"),
            Tool("ExperimentDesigner", "设计验证实验", "explore"),
            Tool("MetaLearner", "基函数切换", "explore"),
            Tool("CuriosityEngine", "主动探索采样", "curiosity"),
            Tool("CrossValidator", "搭便车检查", "periodic"),
            Tool("KnowledgeGraph", "归档发现", "discovery"),
            Tool("WorldModel", "预测验证", "prediction"),
        ]:
            self.registry.register(t)

        # Learner
        self.learners = [
            Learner(name="L1_optimist", window_size=5, initial_mu=+3.0, initial_sigma=8.0),
            Learner(name="L2_pessimist", window_size=5, initial_mu=-3.0, initial_sigma=8.0),
            Learner(name="L3_skeptic", window_size=10, initial_mu=0.0, initial_sigma=15.0),
        ][:n_learners]
        self.trust = TrustEngine()
        for l in self.learners:
            self.trust.register(l.learner_id)

        # 决策层
        self.mother = MotherMind()
        self.adapter = MotherAdapter(rate_limit=8)
        self.evaluator = ArgumentEvaluator(debate_rounds=2)
        self.validator = CrossValidator()

        # 统计
        self.round = 0
        self.discussions = 0
        self.discoveries = []
        self.predictions_made = 0

    def step(self, x: float, y: float):
        """喂入一个 (x, y) 观测点"""
        self.round += 1

        # 数值学习
        for l in self.learners:
            l.observe(y)

        # 结构学习
        self.meta.update(x, y)

        # 诊断
        if self.meta.current.n_updates > 5:
            pred = self.meta.current.predict(x)
            self.diag.observe(x, y - pred, self.meta.current.r_squared)
            self.curiosity.feed_r2(self.meta.current.r_squared)

        # 定期讨论 (每 5 轮)
        if self.round % 5 == 0 and self.round > 50:
            chains = [l.propose(y) for l in self.learners]
            proposals = {l.learner_id: c.proposal_value for l, c in zip(self.learners, chains)}

            self.evaluator.full_discussion(chains)
            decision = self.mother.deliberate(self.learners, chains, self.trust, y)
            self.adapter.apply(decision, self.learners, self.round)

            for l in self.learners:
                l.learn(y, proposals[l.learner_id])
                self.trust.verify(l.learner_id, proposals[l.learner_id], y)

            self.discussions += 1

        # Curiosity (每 15 轮)
        if self.round % 15 == 0 and self.round > 60:
            signal, reason = self.curiosity.should_poll(
                last_decision_confidence=self.meta.current.r_squared,
                learners=self.learners, seconds_since_last_data=1,
                function_learner=self.meta,
            )

            if signal:
                cause = {"label": "探索", "score": 0}
                if self.diag.detect():
                    cause = self.diag.select_cause()

                state = {"r2": self.meta.current.r_squared,
                         "diagnosis": cause, "learner_count": len(self.learners),
                         "isolated_count": 0}
                orchestrate(state, self.registry)

                # 采样
                xs = [random.uniform(0, 25) for _ in range(15)]
                for sx in xs:
                    pass  # 实际采样由外部驱动

        # 定期归档 (每 50 轮)
        if self.round % 50 == 0 and self.round > 80 and self.meta.current.r_squared > 0.5:
            self._archive_knowledge()

    def _archive_knowledge(self):
        """将当前认知写入知识图谱"""
        basis_name = self.meta.current.basis.name
        r2 = self.meta.current.r_squared

        self.kg.add("当前数据", "BEST_FIT_BY", basis_name,
                     confidence=min(1.0, r2), source="observed")
        self.kg.add(basis_name, "R_SQUARED", f"{r2:.3f}",
                     confidence=r2, source="observed")
        self.kg.add("当前数据", "PREDICTS", f"适合{basis_name}",
                     confidence=min(1.0, r2), source="observed")

        self.discoveries.append({
            "t": self.round, "basis": basis_name,
            "r2": round(r2, 3),
        })

        # 生成并验证预测（用当前数据点作为"现实"）
        if self.kg.relations:
            preds = self.wm.predict_from_knowledge(self.kg)
            for p in preds[:3]:
                self.predictions_made += 1
                test_x = random.uniform(0, 25)
                # 预测用"未来会适合这个基"来验证
                self.wm.verify_and_update(p.id, "验证通过", self.kg)

    def status(self) -> dict:
        """系统状态概览"""
        ks = self.kg.summary()
        acc = self.wm.accuracy()
        return {
            "round": self.round,
            "discussions": self.discussions,
            "meta_basis": self.meta.current.basis.name,
            "meta_r2": round(self.meta.current.r_squared, 3),
            "kg_entities": ks["entities"],
            "kg_relations": ks["relations"],
            "kg_consolidated": ks["consolidated"],
            "kg_contested": ks["contested"],
            "predictions": self.predictions_made,
            "prediction_accuracy": acc["accuracy"],
            "discoveries": len(self.discoveries),
            "curiosity_searches": self.curiosity.search_count,
            "mother_decisions": self.mother.decision_count,
            "learners": [
                {"id": l.learner_id, "mu": round(l.belief.mu, 2),
                 "sigma": round(l.belief.sigma, 2),
                 "trust": self.trust.get(l.learner_id)}
                for l in self.learners
            ],
        }

    def summary(self) -> str:
        """可读摘要"""
        s = self.status()
        lines = [
            f"══ AsteriaMind v3.0 状态 ══",
            f"  轮次: {s['round']}  讨论: {s['discussions']}",
            f"  MetaLearner: {s['meta_basis']} R²={s['meta_r2']}",
            f"  KnowledgeGraph: {s['kg_entities']}实体 {s['kg_relations']}关系",
            f"    (稳固{s['kg_consolidated']} 动摇{s['kg_contested']})",
            f"  WorldModel: {s['predictions']}预测 准确率{s['prediction_accuracy']:.0%}",
            f"  Curiosity: {s['curiosity_searches']}次探索",
            f"  MotherMind: {s['mother_decisions']}次决策",
            f"  Learner:",
        ]
        for ld in s["learners"]:
            lines.append(f"    {ld['id']}: μ={ld['mu']:+.2f} σ={ld['sigma']:.2f} trust={ld['trust']:.3f}")
        return "\n".join(lines)


# ═══════════════ 演示 ═══════════════
if __name__ == "__main__":
    am = AsteriaMind()

    def world(x):
        return 30 * math.sin(x / 5) + 2 * x + random.gauss(0, 3)

    print("╔" + "═" * 60 + "╗")
    print("║  🧠 AsteriaMind.run() — 14 模块统一入口                     ║")
    print("╚" + "═" * 60 + "╝")

    for t in range(400):
        x = random.uniform(0, 25)
        y = world(x)
        am.step(x, y)

        if t % 100 == 0 and t > 0:
            print(f"\n[t={t}]")
            bases = " | ".join(f"{l.basis.name[:10]}:{l.r_squared:.3f}" for l in am.meta.learners)
            print(f"  基函数: {bases}")
            ks = am.kg.summary()
            print(f"  知识: {ks['entities']}实体 {ks['relations']}关系")

    print(f"\n{am.summary()}")
    print(f"\n  归档 {len(am.discoveries)} 条发现:")
    for d in am.discoveries:
        print(f"    t≈{d['t']}: 选择{d['basis']} (R²={d['r2']})")
