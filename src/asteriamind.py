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

from hivemind_v2.knowledge import KnowledgeGraph
from hivemind_v2.world_model import WorldModel
from hivemind_v2.meta_learner import MetaLearner, BasisSet
from hivemind_v2.poly_learner import PolyLearner
from hivemind_v2.diagnosis import DiagnosticEngine, ExperimentDesigner
from hivemind_v2.tool_registry import ToolRegistry, Tool, orchestrate
from hivemind_v2.mother_adapter import MotherAdapter
from hivemind_v2.learner import Learner
from hivemind_v2.trust import TrustEngine
from hivemind_v2.mother import MotherMind
from hivemind_v2.argument import ArgumentEvaluator
from hivemind_v2.validator import CrossValidator
from hivemind_v2.portal import CuriosityEngine
from hivemind_v2.exploration_reward import DelayedVerificationQueue, ExplorationReward

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

    def do_explore(self, arg):
        """自主提问 → 实验 → 闭环: explore"""
        print("\n════════════════════════════════════════════")
        print("🔬 AM 自主探索 — 完整闭环")
        print("════════════════════════════════════════════")

        # ── Step 1: 发现知识缺口 ──
        uncertain = kg.most_uncertain(5)
        if not uncertain:
            # 如果图是空的, 先喂一些基础数据
            print("\n  ⚠️  知识图谱是空的。先用世界模型喂数据建立基础认知...")
            def world(x):
                return 30 * math.sin(x / 5) + 2 * x + random.gauss(0, 3)

            for _ in range(60):
                x = random.uniform(0, 25)
                y = world(x)
                step(x, y)
            basis_name = meta.current.basis.name
            r2 = meta.current.r_squared
            kg.add("当前数据", "BEST_FIT_BY", basis_name, confidence=min(1.0, r2), source="observed")
            kg.add("当前数据", "PREDICTS", f"适合{basis_name}", confidence=min(1.0, r2), source="observed")
            print(f"  ✅ 基础认知建立: 数据似乎适合 {basis_name} (R²={r2:.3f})")
            uncertain = kg.most_uncertain(5)

        if not uncertain:
            print("  ❌ 仍然没有可探索的知识。")
            return

        target = uncertain[0]
        print(f"""
  🔍 步骤 1: 发现知识缺口
    最不确定的知识: {target.key()}
    当前置信度: {target.confidence:.2f}
    信念: α={target.belief.alpha:.1f} β={target.belief.beta:.1f}
""")

        # ── Step 2: 生成假说 ──
        if target.predicate == "PREDICTS":
            question = f"在什么条件下 {target.subject} 会导致 {target.object}？"
            hypo = f"假说: {target.subject} 总导致 {target.object}"
            alt = f"反假说: {target.subject} 不一定导致 {target.object}"
        elif target.predicate == "CAUSES":
            question = f"为什么 {target.subject} 会导致 {target.object}？"
            hypo = f"假说: {target.subject} 直接导致 {target.object}"
            alt = f"反假说: {target.subject} 和 {target.object} 只是相关性"
        elif target.predicate == "BEST_FIT_BY":
            question = f"数据是否真的最适合 {target.object}？"
            hypo = f"假说: 当前数据最适合 {target.object}"
            alt = f"反假说: 换一种基函数可能更好"
        else:
            question = f"{target.key()} 是否成立？"
            hypo = f"假说: {target.key()} 成立"
            alt = f"反假说: {target.key()} 不成立"

        print(f"""  ❓ 步骤 2: 生成问题
    "{question}"
    {hypo}
    {alt}
""")

        # ── Step 3: 设计实验 ──
        print(f"  🧪 步骤 3: 设计实验")
        if "BEST_FIT" in target.predicate or "基函数" in question:
            # 结构实验: 在更多点采样, 比较三个基的 R²
            n_sample = 20
            xs = [random.uniform(0, 25) for _ in range(n_sample)]
            strategy = "全域采样, 比较基函数 R²"
        elif target.predicate in ("PREDICTS", "CAUSES"):
            # 因果实验: 观察 subject 出现时 object 是否也出现
            n_sample = 15
            xs = [random.uniform(0, 25) for _ in range(n_sample)]
            strategy = f"观测 {n_sample} 个数据点, 验证因果关系"
        else:
            n_sample = 10
            xs = [random.uniform(0, 25) for _ in range(n_sample)]
            strategy = "随机采样验证"

        print(f"    策略: {strategy} ×{n_sample}")
        print(f"    采样 {n_sample} 个点...")

        # ── Step 4: 执行实验 ──
        pre_bases = {l.basis.name: l.r_squared for l in meta.learners}
        pre_confidence = target.confidence

        def world(x):
            return 30 * math.sin(x / 5) + 2 * x + random.gauss(0, 3)

        correct_count = 0
        for sx in xs:
            sy = world(sx)
            step(sx, sy)

            # 验证: 如果是结构型, 看最优基是否匹配
            if "BEST_FIT" in target.predicate:
                if meta.current.basis.name == target.object:
                    correct_count += 1

        # ── Step 5: 分析结果 ──
        post_confidence = target.confidence
        post_bases = {l.basis.name: l.r_squared for l in meta.learners}

        if "BEST_FIT" in target.predicate or "基函数" in question:
            # 结构验证
            accuracy = correct_count / n_sample
            if accuracy > 0.6:
                kg.observe(target.subject, target.predicate, target.object, correct=True, weight=1.0)
                verdict = f"✅ 假说成立! {n_sample} 个采样点 {correct_count}/{n_sample} 确认。"
            else:
                best_basis = max(post_bases, key=post_bases.get)
                kg.observe(target.subject, target.predicate, target.object, correct=False,
                           weight=0.5, context=f"实际最优是{best_basis}",
                           alternative=f"更适合{best_basis}")
                verdict = f"❌ 假说被推翻! 实际最优基是 {best_basis}。"
        else:
            # 因果/关系验证
            accuracy = correct_count / max(1, n_sample)
            kg.observe(target.subject, target.predicate, target.object, correct=(accuracy > 0.5),
                       weight=1.0)
            verdict = f"{'✅' if accuracy>0.5 else '❌'} 实验完成 ({correct_count}/{n_sample} 支持)"

        post_confidence = target.confidence
        delta = post_confidence - pre_confidence

        print(f"""
  📊 步骤 4+5: 结果分析
    {verdict}
    置信度: {pre_confidence:.2f} → {post_confidence:.2f} ({delta:+.2f})
    信念: α={target.belief.alpha:.1f} β={target.belief.beta:.1f}
    {'← 更坚定了' if delta > 0.01 else '← 动摇了' if delta < -0.01 else '← 没变化'}
""")

        # ── 步骤 6: 反思 ──
        print(f"  🧠 步骤 6: 反思与归档")
        if delta > 0.02:
            insight = f"对\"{target.key()}\"的信念更坚定了。这条知识被实验证实, 可以作为稳定推断的基础。"
        elif delta < -0.02:
            insight = f"对\"{target.key()}\"的信念被削弱了。应该考虑替代解释, 可能需要学习新知识。"
            kg.add(target.subject, "MIGHT_NOT_BE", target.object,
                   confidence=abs(delta), source="inferred")
        else:
            insight = f"实验没有显著改变信念。需要更多数据或更精准的实验设计。"

        print(f"    💡 {insight}")
        print(f"════════════════════════════════════════════\n")

        # 显示更新后的知识图谱
        print("  更新后的知识图谱:")
        print(kg.dump())

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
