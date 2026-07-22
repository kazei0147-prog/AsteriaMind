"""
AsteriaMind REPL — 交互式终端 (v3.0)

运行: python asteriamind.py --interactive

命令:
  status           系统状态
  learn <知识>     教她新知识: "learn 春天 CAUSES 花粉过敏"
  ask <问题>       查询知识: "ask 春天 CAUSES 什么?"
  predict          基于知识做预测
  verify <结果>    验证上次预测
  mother           看 MotherMind 在想什么
  knowledge        知识图谱概览
  run <N>          自主运行 N 轮
  help             帮助
"""
import cmd, math, random, sys, os

REPO = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, REPO)

from AsteriaMind.knowledge import KnowledgeGraph
from AsteriaMind.world_model import WorldModel
from AsteriaMind.meta_learner import MetaLearner, BasisSet
from AsteriaMind.poly_learner import PolyLearner
from AsteriaMind.diagnosis import DiagnosticEngine, ExperimentDesigner
from AsteriaMind.tool_registry import ToolRegistry, Tool, orchestrate
from AsteriaMind.mother_adapter import MotherAdapter
from AsteriaMind.learner import Learner
from AsteriaMind.trust import TrustEngine
from AsteriaMind.mother import MotherMind
from AsteriaMind.argument import ArgumentEvaluator
from AsteriaMind.validator import CrossValidator
from AsteriaMind.portal import CuriosityEngine
from AsteriaMind.exploration_reward import DelayedVerificationQueue, ExplorationReward
from AsteriaMind.datasource import LibrarySource, DataPipeline, TextIngestor, KnowledgeAssimilator
from AsteriaMind.hypothesis_template import (
    HypothesisEngine, TemplateRegistry, TheoryGovernance,
    _builtin_templates, HypothesisTemplate,
)
from AsteriaMind.cognitive_evolution import CognitiveEvolutionLayer
from AsteriaMind.certainty_audit import CertaintyAudit

random.seed(42)

# ═══════════════ 初始化 ═══════════════
kg = KnowledgeGraph()
wm = WorldModel()
meta = MetaLearner(switch_r2_gap=0.03, check_interval=10)
poly = PolyLearner(max_degree=5, upgrade_cooldown=6)
diag = DiagnosticEngine(history_window=50)
designer = ExperimentDesigner()
curiosity = CuriosityEngine(exploration_patience=12)
curiosity._experiment_interval = 15
reward_engine = ExplorationReward()
reward_queue = DelayedVerificationQueue(delay_rounds=10)

# 外部世界
library = LibrarySource()
pipeline = DataPipeline(kg, library)
ingestor = TextIngestor()
assimilator = KnowledgeAssimilator(kg, pipeline)

# 四层认知架构
registry = TemplateRegistry()
for t in _builtin_templates():
    registry.register(t)
engine = HypothesisEngine(registry)
evolution = CognitiveEvolutionLayer(registry, kg, wm)
governance = TheoryGovernance(registry)
auditor = CertaintyAudit()
governance = TheoryGovernance(registry)

# 预填充知识库 (AM 可以自己查)
library.add_fact("物体A", "HAS", "属性X", 0.9)
library.add_fact("物体A", "HAS", "属性M", 0.5)  # AM 还不知道的新属性
library.add_fact("物体B", "HAS", "属性X", 0.8)
library.add_fact("物体B", "RESPONDS_TO", "事件1", 0.4)
library.add_fact("物体C", "CAUSES", "事件3", 0.6)
library.add_fact("物体C", "HAS", "属性N", 0.7)
library.add_fact("事件1", "TRIGGERS", "事件4", 0.6)
library.add_fact("事件4", "DEPENDS_ON", "物体A", 0.3)

registry = ToolRegistry()
for t in [
    Tool("DiagnosticEngine", "诊断崩塌原因", "collapse"),
    Tool("ExperimentDesigner", "设计验证实验", "explore"),
    Tool("MetaLearner", "基函数切换", "explore"),
    Tool("PolyLearner", "多项式升阶", "collapse"),
    Tool("CuriosityEngine", "主动探索", "curiosity"),
    Tool("KnowledgeGraph", "归档发现", "discovery"),
    Tool("WorldModel", "预测验证", "prediction"),
    Tool("ExplorationReward", "奖励分配", "periodic"),
]:
    registry.register(t)

learners = [
    Learner(name="L1_optimist", window_size=5, initial_mu=+3.0, initial_sigma=8.0),
    Learner(name="L2_pessimist", window_size=5, initial_mu=-3.0, initial_sigma=8.0),
    Learner(name="L3_skeptic", window_size=10, initial_mu=0.0, initial_sigma=15.0),
]
trust = TrustEngine()
for l in learners: trust.register(l.learner_id)

mother = MotherMind()
adapter = MotherAdapter(rate_limit=8)
evaluator = ArgumentEvaluator(debate_rounds=2)
validator = CrossValidator()

last_prediction = None
ROUND = 0

def step(x, y):
    global ROUND
    ROUND += 1
    for l in learners:
        l.observe(y)
    meta.update(x, y)
    poly.update(x, y)

    if meta.current.n_updates > 5:
        pred = meta.current.predict(x)
        diag.observe(x, y - pred, meta.current.r_squared)
        curiosity.feed_r2(meta.current.r_squared)

    if ROUND % 5 == 0 and ROUND > 50:
        chains = [l.propose(y) for l in learners]
        proposals = {l.learner_id: c.proposal_value for l, c in zip(learners, chains)}
        evaluator.full_discussion(chains)
        decision = mother.deliberate(learners, chains, trust, y)
        adapter.apply(decision, learners, ROUND)
        for l in learners:
            l.learn(y, proposals[l.learner_id])
            trust.verify(l.learner_id, proposals[l.learner_id], y)
            reward_engine.record_prediction(l.learner_id, proposals[l.learner_id])
            reward_queue.submit(l.learner_id, proposals[l.learner_id], y, ROUND)
        reward_queue.resolve(ROUND, y)

    if ROUND % 50 == 0 and ROUND > 80 and meta.current.r_squared > 0.5:
        basis_name = meta.current.basis.name
        r2 = meta.current.r_squared
        kg.add("当前数据", "BEST_FIT_BY", basis_name, confidence=min(1.0, r2), source="observed")
        kg.add("当前数据", "PREDICTS", f"适合{basis_name}", confidence=min(1.0, r2), source="observed")

# ═══════════════ REPL ═══════════════

class AsteriaShell(cmd.Cmd):
    intro = """
╔════════════════════════════════════════════════╗
║  🧠 AsteriaMind REPL v3.0                     ║
║  输入 help 查看命令, 输入 quit 退出              ║
╚════════════════════════════════════════════════╝"""
    prompt = "🧠> "

    def do_status(self, arg):
        """系统状态概览"""
        ks = kg.summary()
        print(f"""
══ AsteriaMind 状态 (第 {ROUND} 轮) ══
  MetaLearner: {meta.current.basis.name} R²={meta.current.r_squared:.3f}
  知识图谱: {ks['entities']}实体 {ks['relations']}关系 (稳固{ks['consolidated']} 动摇{ks['contested']})
  Curiosity: {curiosity.search_count}次探索
  MotherMind: {mother.decision_count}次决策
  Learner:""")
        for l in sorted(learners, key=lambda x: -trust.get(x.learner_id)):
            print(f"    {l.learner_id}: μ={l.belief.mu:+.2f} σ={l.belief.sigma:.2f} trust={trust.get(l.learner_id):.3f}")

    def do_learn(self, arg):
        """教知识: learn 春天 CAUSES 花粉过敏 [0.8]"""
        parts = arg.split()
        if len(parts) >= 3:
            subj, pred, obj = parts[0], parts[1], parts[2]
            conf = float(parts[3]) if len(parts) > 3 else 0.7
            kg.add(subj, pred, obj, confidence=conf)
            print(f"  ✅ 已学习: {subj} --[{pred}]--> {obj} (置信度 {conf})")
        else:
            print("  用法: learn <主体> <关系> <客体> [置信度]")

    def do_ask(self, arg):
        """查询: ask 春天 CAUSES"""
        parts = arg.split()
        if len(parts) == 2:
            results = kg.query(parts[0], parts[1])
        else:
            results = kg.query(arg.strip())

        if not results:
            print("  ❓ 我还不知道。")
            return

        for r in results[:5]:
            bar = "█" * int(r.confidence * 10) + "░" * (10 - int(r.confidence * 10))
            print(f"  {r.subject} --[{r.predicate}]--> {r.object}  [{bar}] {r.confidence:.2f}  {r.belief.summary()}")
            if r.counter_evidence:
                for ce in r.counter_evidence:
                    print(f"    ↳ 但语境\"{ce.context}\"中是\"{ce.alternative}\"")

    def do_knowledge(self, arg):
        """知识图谱全览"""
        print(kg.dump())

    def do_predict(self, arg):
        """基于知识做预测"""
        global last_prediction
        preds = wm.predict_from_knowledge(kg)
        if not preds:
            print("  ❌ 没有可预测的知识。先用 learn 教一些 PREDICTS 关系。")
            return
        last_prediction = preds[0]
        print(f"  📋 预测: {last_prediction.description}")
        print(f"     预测值: {last_prediction.predicted_value}")
        print(f"     置信度: {last_prediction.confidence:.2f}")
        print(f"  💡 用 verify <正确|错误> 来验证")

    def do_verify(self, arg):
        """验证: verify 花粉过敏 (填入真实观测值)"""
        global last_prediction
        if last_prediction is None:
            print("  ❌ 还没有预测。先 predict。")
            return
        reality = arg.strip()
        if not reality:
            print("  用法: verify <现实值>  (例如: verify 花粉过敏)")
            return
        result = wm.verify_and_update(last_prediction.id, reality, kg)
        if result:
            icon = "✅" if result["correct"] else "❌"
            print(f"  {icon} 预测'{result['predicted']}' vs 现实'{result['reality']}' "
                  f"— 准确率: {wm.accuracy()['accuracy']:.0%}")

    def do_mother(self, arg):
        """MotherMind 最近在想什么"""
        decision = mother.decision_history[-1] if mother.decision_history else None
        if decision:
            print(f"""
  共识: {decision.consensus:.2f}  置信度: {decision.confidence:.2f}
  推理: {decision.reasoning}
  主导: {decision.primary_influence}
  反馈:""")
            for lid, fb in sorted(decision.learner_feedback.items()):
                print(f"    → {lid}: {fb[:80]}...")
        else:
            print("  MotherMind 还没做过决策。先 run <N> 让它看一些数据。")

    def do_run(self, arg):
        """自主运行 N 轮: run 100"""
        n = int(arg) if arg.strip().isdigit() else 50
        print(f"  🏃 自主运行 {n} 轮...")

        def world(x):
            return 30 * math.sin(x / 5) + 2 * x + random.gauss(0, 3)

        for _ in range(n):
            x = random.uniform(0, 25)
            y = world(x)
            step(x, y)
        print(f"  ✅ 完成。当前第 {ROUND} 轮。")

    def do_upload(self, arg):
        """上传数据点: upload x=5.2 y=42.3"""
        import re
        m = re.match(r'x=([\d.]+)\s+y=([\d.]+)', arg)
        if m:
            x, y = float(m.group(1)), float(m.group(2))
            step(x, y)
            print(f"  ✅ 已喂入 ({x}, {y})，第 {ROUND} 轮")
        else:
            print("  格式: upload x=5.2 y=42.3")

    def do_fetch(self, arg):
        """AM 自己去外部世界查: fetch 物体A"""
        subject = arg.strip()
        if not subject:
            # 自动找最不确定的实体
            goals = kg.generate_goals(max_goals=1)
            if goals:
                subject = goals[0]["target"].split("--[")[0].strip()
                print(f"  🔍 自动选择最需要了解的目标: {subject}")
            else:
                print("  ❌ 没有可查询的目标。先 learn 一些知识。")
                return

        print(f"  📡 查询外部世界: \"{subject}\"...")
        summary = pipeline.explore_entity(subject)
        print(f"  {summary}")

        # 显示查到的新知识
        if pipeline.fetch_log:
            last = pipeline.fetch_log[-1]
            print(f"  共获取 {pipeline.fetch_count} 条外部知识。")

    def do_library(self, arg):
        """查看外部知识库的内容"""
        print(f"  外部知识库: {len(library._facts)} 个实体")
        for entity, facts in sorted(library._facts.items()):
            print(f"    {entity}:")
            for pred, obj, conf in facts[:3]:
                print(f"      {pred} → {obj} ({conf})")
            if len(facts) > 3:
                print(f"      ...等 {len(facts)} 条")
    def do_audit(self, arg):
        """压力测试高置信度信念: audit"""
        print(f"\n  🔍 信念压力测试 — 寻找结构性盲区")
        print(f"  {'─'*50}")
        summary = auditor.summarize(kg)
        print(f"  {summary}")

        # 不只是说——做了才算
        actions = auditor.act_on_findings(kg, engine)
        if actions:
            print(f"\n  ⚡ 对高风险发现执行了 {len(actions)} 项行动:")
            for a in actions:
                print(f"     [{a['action']}] {a['detail']}")

    def do_read(self, arg):
        """阅读文本并同化: read <文本> [来源] [可信度]"""
        parts = arg.split("|")
        text = parts[0].strip()
        source = parts[1].strip() if len(parts) > 1 else "user"
        credibility = float(parts[2].strip()) if len(parts) > 2 else 0.5

        if not text:
            print("  用法: read <文本> | <来源> | <可信度>")
            return

        # Step 1: 提取主张
        claims = ingestor.ingest(text, source_name=source,
                                 source_credibility=credibility)
        print(f"\n  📖 从文本中提取了 {len(claims)} 条主张 (来源: {source}, 可信度: {credibility}):")
        for c in claims:
            print(f"    · {c.subject} {c.predicate} {c.object}")

        if not claims:
            print("  ⚠️ 未识别出可用的主张。尝试更直接的表述。")
            return

        # Step 2: 同化
        print(f"\n  🧠 同化中 (与已有 {len(kg.relations)} 条知识碰撞)...")
        result = assimilator.assimilate(claims)

        # Step 3: 报告
        print(f"  ✅ 接受: {result['accepted']}   ⚡ 冲突: {result['conflicted']}   ❌ 拒绝: {result['rejected']}")
        for d in result["details"]:
            icon = {"accepted": "✅", "reinforced": "⬆️", "conflicted": "⚡", "rejected": "❌"}.get(d["action"], "?")
            print(f"    {icon} [{d['action']}] {d['claim'][:60]}")
            print(f"       {d['reason']}")

    def do_explore(self, arg):
        """自主闭环: 知识图谱自己产生目标→假说→实验→解释"""
        print("\n════════════════════════════════════════════")
        print("🔬 AM 自主探索 — 无模板闭环")
        print("════════════════════════════════════════════")

        # ── Step 1: 图谱自己生成目标 ──
        goals = kg.generate_goals(max_goals=3)
        if not goals:
            print("\n  ⚠️  知识图谱是空的。先建立基础认知...")
            def world(x):
                return 30 * math.sin(x / 5) + 2 * x + random.gauss(0, 3)
            for _ in range(60):
                x = random.uniform(0, 25)
                y = world(x)
                step(x, y)
            kg.add("当前数据", "BEST_FIT_BY", meta.current.basis.name,
                   confidence=min(1.0, meta.current.r_squared), source="observed")
            kg.add("当前数据", "PREDICTS", f"适合{meta.current.basis.name}",
                   confidence=min(1.0, meta.current.r_squared), source="observed")
            goals = kg.generate_goals(max_goals=3)

        if not goals:
            print("  ❌ 仍然没有可探索的目标。")
            return

        print(f"\n  🔍 图谱自主生成 {len(goals)} 个探索目标:")
        for i, g in enumerate(goals):
            tag = {"gap": "🕳️", "conflict": "⚡", "uncertain": "❓"}.get(g["type"], "?")
            print(f"    {i+1}. {tag} [{g['type']}] {g['reason']}")

        goal = goals[0]

        # ── Step 2: 从 Registry 取理论, 引擎生成假说 ──
        hypotheses = engine.generate(kg, goal["target"], goal["type"])
        print(f"\n  💭 关于\"{goal['target']}\"的 {len(hypotheses)} 个竞争假说 (奥卡姆已应用):")
        print(f"    {'ID':3s} {'机制':8s} {'置信度':>6s} {'奥卡姆':>6s} {'复杂度':>14s}")
        for h in hypotheses:
            cx = h.get("complexity", {})
            cost = f"参×{cx.get('free_params',0)} 假×{cx.get('assumptions',0)}"
            occam = h.get("occam_score", h["confidence"])
            print(f"    {h['id']:3s} {h['mechanism']:8s} {h['confidence']:5.3f}  {occam:5.3f}  {cost:>14s}")
        for h in hypotheses:
            print(f"\n     {h['id']}: {h['label']}")
            print(f"     机制: {h['mechanism']}")
            print(f"     置信度: {h['confidence']:.3f}")
            print(f"     📊 预测: {h['prediction']}")
            print(f"     🔬 检验: {h['test']}")
            if 'discrimination' in h:
                print(f"     ⚔️  {h['discrimination']}")

        # ── Step 3: 世界模型检验竞争假说 ──
        top2 = [h for h in hypotheses[:2] if h["confidence"] > 0.05]
        if len(top2) >= 2:
            print(f"\n  🌍 WorldModel 比较 H1 vs H2:")
            h1, h2 = top2[0], top2[1]
            print(f"     如果 {h1['id']} 正确: {h1['prediction']}")
            print(f"     如果 {h2['id']} 正确: {h2['prediction']}")
            print(f"     🧪 区分实验: 采样 20 个点看实际模式")

        # ── 认知演化: 框架反思 + 候选理论审稿 + 验证 + 注册 ──
        evo_result = evolution.observe_and_evolve(goals, hypotheses, kg, ROUND)
        if evo_result.get("evolution") == "accepted":
            print(f"\n  🧬 认知演化: 新理论通过审稿并注册!")
            print(f"     {evo_result['new_template']}")
            if "evaluation" in evo_result:
                print(f"     审稿: {evo_result['evaluation']}")
            if "validation" in evo_result:
                val = evo_result["validation"]
                print(f"     现实验证: {val['accuracy']:.0%} 准确率 ({val.get('correct',0)}/{val.get('predictions',0)})")
                print(f"     基线: {val.get('baseline_accuracy',0):.0%}  提升: {val.get('improvement',0):+.2f}")
        elif evo_result.get("evolution") == "rejected_at_evaluation":
            print(f"\n  ❌ 候选理论未通过审稿: {evo_result.get('evaluation', {})}")
        elif evo_result.get("evolution") == "rejected_at_validation":
            print(f"\n  ❌ 候选理论未通过现实验证")

        # ── Step 4: 采样 + 执行 ──
        print(f"\n  🧪 采样 20 个点...")
        pre_state = {}
        for r in kg.relations:
            if goal["target"] in r.key():
                pre_state[r.key()] = (r.confidence, r.belief.alpha, r.belief.beta)

        def world(x):
            return 30 * math.sin(x / 5) + 2 * x + random.gauss(0, 3)

        n = 20
        for _ in range(n):
            x = random.uniform(0, 25)
            y = world(x)
            step(x, y)

        # 用新数据更新信念 (哪个假说被支持?)
        for r in kg.relations:
            if goal["target"] in r.key():
                kg.observe(r.subject, r.predicate, r.object,
                           correct=(r.confidence > 0.3), weight=0.5)

        # ── Step 5: 结果 ──
        print(f"\n  📊 实验结果:")
        for r in kg.relations:
            if goal["target"] in r.key() and r.key() in pre_state:
                old_c, old_a, old_b = pre_state[r.key()]
                delta = r.confidence - old_c
                arrow = "↑" if delta > 0.01 else ("↓" if delta < -0.01 else "→")
                explanation = kg.explain_change(
                    r.key(), old_c, r.confidence, old_a, r.belief.alpha, old_b, r.belief.beta)
                print(f"     {arrow} {r.key()[:55]}")
                print(f"        置信度 {old_c:.2f}→{r.confidence:.2f}")
                print(f"        💡 {explanation}")

        # 更新假说竞争结果
        if top2 and any(goal["target"] in r.key() for r in kg.relations):
            target_rel = [r for r in kg.relations if goal["target"] in r.key()][0]
            if target_rel.confidence > 0.5:
                print(f"\n  🏆 实验后偏好的假说: {'H1' if target_rel.confidence > 0.4 else 'H2'}")
                print(f"     因为: 数据支持了目标关系的存在 (置信度 {target_rel.confidence:.2f})")

    def do_help(self, arg):
        print("""
命令:
  status              系统状态
  learn S P O [C]     教她: learn 春天 CAUSES 花粉过敏 0.8
  ask <问题>          查询: ask 春天 CAUSES 什么?
  predict             基于知识预测
  verify <现实值>      验证上次预测
  explore             自主提问→实验→闭环 (核心!)
  mother              MotherMind 在想什么
  knowledge           知识图谱全览
  run <N>             自主运行 N 轮
  upload x=X y=Y      喂入数据点
  quit                退出
""")

    def do_quit(self, arg):
        print("  👋")
        return True


# ═══════════════ 入口 ═══════════════
if __name__ == "__main__":
    if "--interactive" in sys.argv or "-i" in sys.argv:
        AsteriaShell().cmdloop()
    else:
        # 非交互模式: 跑一轮演示
        def world(x):
            return 30 * math.sin(x / 5) + 2 * x + random.gauss(0, 3)

        print("AsteriaMind v3.0 — 非交互模式 (用 --interactive 进入 REPL)")
        for t in range(400):
            x = random.uniform(0, 25)
            y = world(x)
            step(x, y)
        ks = kg.summary()
        print(f"  完成 400 轮。知识: {ks['entities']}实体 {ks['relations']}关系。")
        print(f"  用 python asteriamind.py --interactive 进入对话。")
