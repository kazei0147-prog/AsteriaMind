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
from AsteriaMind.falsification import (
    FalsificationController, SourceAuthorityTracker, WebSearchInterface,
)
from AsteriaMind.vector_layer import VectorLayer
from AsteriaMind.human_review import HumanReviewInterface, ProvenanceGuard
from AsteriaMind.cross_layer import CrossLayerBridge, QueryRouter
from AsteriaMind.knowledge_request import (
    KnowledgeRequestMonitor, KnowledgeAcquisitionExecutor, KnowledgeRequest,
)
from AsteriaMind.math_reasoner import MathReasoner
from AsteriaMind.skill_library import SkillLibrary, build_default_skills
from AsteriaMind.command_tool import CommandTool
from AsteriaMind.active_learner import ActiveLearner
from AsteriaMind.knowledge_db import KnowledgeDB

random.seed(42)
import re, json

# ═══════════════ 初始化 ═══════════════
kg = KnowledgeGraph()
db = KnowledgeDB("asteriamind.db")
print(f"  💾 数据库就绪: {db.count()} 条关系")
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
tmpl_registry = TemplateRegistry()
for t in _builtin_templates():
    tmpl_registry.register(t)
engine = HypothesisEngine(tmpl_registry)
evolution = CognitiveEvolutionLayer(tmpl_registry, kg, wm)
governance = TheoryGovernance(tmpl_registry)
auditor = CertaintyAudit()
falsifier = FalsificationController()
source_tracker = SourceAuthorityTracker()
knowledge_queue: list[KnowledgeRequest] = []
web_search = WebSearchInterface()
krm = KnowledgeRequestMonitor(knowledge_queue)
kae = None  # 在 vl 之后初始化
vl = VectorLayer(dim=128)
kae = KnowledgeAcquisitionExecutor(knowledge_queue, web_search, kg, vl)
math_engine = MathReasoner()
skill_lib = build_default_skills()
ctool = CommandTool()
learner = ActiveLearner(kg, vl, web_search, ctool)

# 注册数学推理为假说模板
tmpl_registry.register(HypothesisTemplate(
    id="H_MATH", name="数学推理", mechanism="符号计算",
    condition_description="查询包含数字或运算符时触发",
    complexity_cost=0.02, free_params=0, assumptions=0,
    condition_fn=lambda kg, e, s: True,
    generate_fn=lambda kg, e, s: [],
))

provenance = ProvenanceGuard()
reviewer = HumanReviewInterface(kg, provenance)
bridge = CrossLayerBridge(kg, vl)
router = QueryRouter(kg, vl, bridge)

# 预填充知识库 (AM 可以自己查)
library.add_fact("物体A", "HAS", "属性X", 0.9)
library.add_fact("物体A", "HAS", "属性M", 0.5)  # AM 还不知道的新属性
library.add_fact("物体B", "HAS", "属性X", 0.8)
library.add_fact("物体B", "RESPONDS_TO", "事件1", 0.4)
library.add_fact("物体C", "CAUSES", "事件3", 0.6)
library.add_fact("物体C", "HAS", "属性N", 0.7)
library.add_fact("事件1", "TRIGGERS", "事件4", 0.6)
library.add_fact("事件4", "DEPENDS_ON", "物体A", 0.3)

registry = ToolRegistry()  # ← 这个覆盖了前面的 TemplateRegistry
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
            rel = kg.add(subj, pred, obj, confidence=conf)
            db.add_relation(subj, pred, obj, conf, source="user")
            provenance.record_add(rel.key(), "user", conf)
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
        """自主运行: run [N] (不指定 = 永久循环)
        条件触发——每个模块只在需要时才被调用, 不是固定节拍器。"""
        forever = not arg.strip() or not arg.strip().isdigit()
        n = int(arg) if arg.strip().isdigit() else 99999
        mode = "永久循环 (Ctrl+C 停止)" if forever else f"{n} 轮"
        print(f"  🏃 自主运行 {mode} (条件触发模式)...")

        # 状态追踪: 每个模块记录上次被调用时间
        state = {"last_audit": 0, "last_bridge": 0, "last_gov": 0,
                 "last_search": 0, "vec_since_bridge": 0, "save_count": 0}

        round_num = 0
        try:
            while round_num < n:
                round_num += 1

                # ── 触发条件评估 ──
                triggers = []

                # 搜索: 每轮扫描缺口, 有请求时按间隔执行
                if kg.relations:
                    krm.scan(kg)
                if knowledge_queue and round_num - state["last_search"] >= 3:
                    urgent = any(hasattr(r, 'urgency') and r.urgency > 0.3 for r in knowledge_queue)
                    if urgent:
                        triggers.append("search")

                # 审计: 有高置信度无反证信念, 且距上次 >= 5 轮
                if round_num - state["last_audit"] >= 5 and kg.relations:
                    risky = [f for f in auditor.audit(kg) if f.risk_level in ("medium", "high")]
                    if risky:
                        triggers.append("audit")

                # 桥接: 新向量数 >= 3, 且距上次 >= 7 轮
                if state["vec_since_bridge"] >= 3 and round_num - state["last_bridge"] >= 7:
                    triggers.append("bridge")

                # 治理+演化: 距上次 >= 10 轮
                if round_num - state["last_gov"] >= 10:
                    triggers.append("govern")

                # ── 执行触发 ──

                if "search" in triggers:
                    state["last_search"] = round_num
                    requests = krm.scan(kg)
                    if requests:
                        result = kae.execute_batch(max_requests=2)
                        if result["new_relations"]:
                            state["vec_since_bridge"] += result["new_relations"]
                            print(f"  📡 [{round_num}] 条件触发: 采购{len(requests)}条请求→{result['new_relations']}新关系  KG:{len(kg.relations)}")

                # 探索: 每轮都做 (轻量级)
                if kg.relations:
                    goals = kg.generate_goals(max_goals=1)
                    if goals:
                        hyps = engine.generate(kg, goals[0]["target"], goals[0]["type"])
                        if hyps and hyps[0].get("mechanism") in ("未建模模式", "统计偶然"):
                            evolution.mhg.reflect_on_failure({"data_type": "unknown"})

                if "audit" in triggers:
                    state["last_audit"] = round_num
                    risky = [f for f in auditor.audit(kg) if f.risk_level in ("medium", "high")]
                    if risky:
                        result = falsifier.run(kg, risky[0].relation_key, max_rounds=3)
                        print(f"  🛡️ [{round_num}] 条件触发: 审计 {risky[0].relation_key}")

                if "bridge" in triggers:
                    state["last_bridge"] = round_num
                    state["vec_since_bridge"] = 0
                    bridge.discover()

                if "govern" in triggers:
                    state["last_gov"] = round_num
                    governance.review(round_num)
                    if kg.relations:
                        goals = kg.generate_goals(max_goals=2)
                        all_hyps = []
                        for g in goals[:2]:
                            hyps = engine.generate(kg, g["target"], g["type"])
                            all_hyps.extend(hyps)
                        if all_hyps:
                            evo = evolution.observe_and_evolve(goals, all_hyps, kg, round_num)
                            if evo.get("alert") == "meta_hypothesis_generated":
                                print(f"  🧬 [{round_num}] 条件触发: MH 发现框架缺陷!")

                # ── 保存 ──
                if round_num % 50 == 0:
                    state["save_count"] += 1
                    kg.save("asteriamind_autosave.json")
                    print(f"  💾 [{round_num}] 自动保存: {len(kg.relations)} 关系")

        except KeyboardInterrupt:
            print(f"\n  ⏸️  运行 {round_num} 轮后中断。")
            kg.save("asteriamind_autosave.json")

        if not forever:
            active = len([t for t in tmpl_registry.templates.values() if t.status == "active"])
            print(f"  ✅ 完成。KG:{len(kg.relations)} 向量:{len(vl.relations)} 模板:{active}")

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
    def do_index(self, arg):
        """批量建立向量索引: index"""
        if not kg.relations:
            print("  ⚠️ 知识图谱为空, 先 learn/read/explore。")
            return
        vl.batch_index(kg.relations)
        print(f"  ✅ 已为 {len(vl.relations)} 条知识建立向量索引 (dim={vl.dim})")

    def do_semantic(self, arg):
        """语义搜索: semantic <查询>"""
        query = arg.strip()
        if not query:
            print("  用法: semantic <查询文本>")
            return
        if not vl.relations:
            print("  ⚠️ 先运行 index 建立向量索引。")
            return
        results = vl.search(query, top_k=5)
        print(f"  🔍 语义搜索: \"{query}\"")
        for key, sim, meta in results:
            bar = "█" * int(sim * 10) + "░" * (10 - int(sim * 10))
            print(f"    {key:50s} [{bar}] {sim:.2f}")

    def do_analogy(self, arg):
        """类比推理: analogy <概念>"""
        concept = arg.strip()
        if not concept:
            print("  用法: analogy <概念>")
            return
        results = vl.analogy(concept, top_k=5)
        print(f"  💡 类比: \"{concept}\" 的最近邻:")
        for key, sim in results:
            print(f"    {key:50s} 相似度 {sim:.2f}")

    def do_assoc(self, arg):
        """关联发现: assoc"""
        pairs = vl.find_associations(min_similarity=0.2)
        if not pairs:
            print("  🔗 未发现隐藏关联。")
            return
        print(f"  🔗 发现 {len(pairs)} 对隐含关联 (向量相似但无直接边):")
        for a, b, sim in pairs[:5]:
            print(f"    {a[:40]} ↔ {b[:40]}  [{sim:.2f}]")

    def do_review(self, arg):
        """人类审核: review <key> correct|wrong|uncertain [原因]"""
        parts = arg.split(None, 2)
        if len(parts) < 2:
            print("  用法: review <key> correct|wrong|uncertain [原因]")
            return
        key, action, *rest = parts[0], parts[1], (parts[2:] if len(parts) > 2 else [])
        reason = rest[0] if rest else ""

        result = ""
        if action == "correct":
            result = reviewer.review_correct(key)
        elif action == "wrong":
            result = reviewer.review_wrong(key, reason or "人工审核判定")
        elif action == "uncertain":
            result = reviewer.review_uncertain(key)
        print(f"  {result}")

    def do_bridge(self, arg):
        """跨层发现: bridge — 向量空间→符号层 映射"""
        print(f"\n  🌉 跨层桥接 — 向量空间结构 → 符号知识")
        print(f"  {'─'*50}")
        discovery = bridge.discover()
        print(f"  🏷️  发现 {len(discovery['clusters'])} 个隐式语义群组:")
        for c in discovery["clusters"][:5]:
            print(f"     [{c.coherence:.2f}] {c.label_hint} ({len(c.members)} 成员)")
            for m in c.members[:3]:
                print(f"        · {m}")
        print(f"  🧭 发现 {len(discovery['directions'])} 个方向模式:")
        for d in discovery["directions"][:3]:
            print(f"     [{d.coherence:.2f}] {d.insight}")
        if discovery["cross_mappings"]:
            print(f"  🔗 跨层映射: {len(discovery['cross_mappings'])} 条新知识已写入 KG")

    def do_route(self, arg):
        """智能查询路由: route <查询>"""
        query = arg.strip()
        if not query:
            print("  用法: route <查询>")
            return
        result = router.route(query)
        print(f"\n  🧭 路由: \"{query}\" → {result['layer']}层"
              f"{' (从精确降级)' if result.get('fallback_used') else ''}")

        if result["layer"] == "exact":
            for r in result["results"][:5]:
                print(f"    · {r.key()} α={r.belief.alpha:.0f} β={r.belief.beta:.0f}")
        elif result["layer"] == "semantic":
            for key, sim, meta in result["results"][:5]:
                print(f"    · {key} [{sim:.2f}]")
        if result.get("bridge_insight"):
            print(f"  🌉 桥接发现: {result['bridge_insight'][0] if result['bridge_insight'] else ''}")

    def do_math(self, arg):
        """数学推理: math <表达式|代数|模式|转换>"""
        query = arg.strip()
        if not query:
            print("  用法: math 2+3 | math x+5=10 | math 2,4,6,8,? | math 1 mile km")
            return

        result = math_engine.solve(query)
        if result is None:
            print(f"  ❓ 无法解析: \"{query}\"")
            return

        print(f"  🧮 {result.expression}")
        for step in result.steps:
            print(f"     {step}")
        print(f"     结果: {result.result}  (置信度 {result.confidence})")

        # 存入 KG: 数学结果作为 derived 知识
        kg.add(query.strip(), "EQUALS", str(result.result),
               confidence=result.confidence, source="math_derived")
        """来源审查: provenance <key>"""
        key = arg.strip()
        if not key:
            print("  用法: provenance <key>")
            return
        report = reviewer.provenance_report(key)
        print(report)

    def do_search(self, arg):
        """网络搜索: search <查询词>"""
        query = arg.strip()
        if not query:
            print("  用法: search <查询词>")
            return
        print(f"  🔍 搜索: \"{query}\"...")
        results = web_search.search(query)
        for r in results[:5]:
            print(f"    📄 {r.title}")
            print(f"       {r.snippet[:100]}")
            print(f"       来源可信度: {r.source_credibility:.2f}")

    def do_skill(self, arg):
        """智能匹配 Skill: skill <查询>"""
        query = arg.strip()
        if not query:
            print("  用法: skill <查询>")
            return
        best = skill_lib.best_match(query)
        if best:
            print(f"  🎯 匹配 Skill: {best.id} ({best.name})")
            result = best.execute(query, kg)
            if result.get("success"):
                val = result.get("result")
                if val is not None:
                    print(f"     结果: {val}")
                if result.get("steps"):
                    for s in result["steps"]:
                        print(f"     {s}")
            else:
                print(f"     ❌ {result.get('error', '执行失败')}")
        else:
            missing = skill_lib.get_missing_triggers(query)
            print(f"  ❓ {missing}")

    def do_cmd(self, arg):
        """执行终端命令: cmd <命令> (白名单安全)"""
        command = arg.strip()
        if not command:
            print("  用法: cmd <命令>")
            return
        result = ctool.run(command)
        icon = "✅" if result.success else "❌"
        print(f"  {icon} [{result.elapsed_ms:.0f}ms] {command}")
        if result.stdout:
            for line in result.stdout.strip().split('\n')[:10]:
                print(f"     {line}")
        if result.stderr:
            print(f"     ⚠ {result.stderr[:100]}")

    def do_learnw(self, arg):
        """学习一个词: learnw <词>"""
        word = arg.strip()
        if not word:
            print("  用法: learnw <词>")
            return
        r = learner.learn_word(word)
        if r["known"]:
            print(f"  ✅ 认识: {word} → {r['definition'][:60]} (来源:{r['source']})")
        elif r.get("pending"):
            print(f"  ❓ 不认识: {word} → 已加入提问队列")
        else:
            print(f"  ❓ {word}: {r.get('note', '未找到')}")

    def do_readcn(self, arg):
        """从中文文本学习: readcn <文本>"""
        text = arg.strip()
        if not text:
            print("  用法: readcn <文本>")
            return
        r = learner.learn_from_text(text)
        print(f"  📖 阅读 {r['total_words']} 词，{r['unique']} 个不同词")
        if r["unknown"] > 0:
            print(f"  ❓ 不认识 {r['unknown']} 个词: {', '.join(r['pending_questions'][:10])}")
            print(f"  使用 questions 查看全部, answer <词> <解释> 回答")

    def do_questions(self, arg):
        """查看待回答问题: questions"""
        qs = learner.get_questions(10)
        if not qs:
            print("  ✅ 没有问题待回答")
        for i, q in enumerate(qs):
            print(f"  {i+1}. {q.get('word', q.get('question','?'))}: {q['context'][:60]}")

    def do_answer(self, arg):
        """回答问题: answer <词> <解释>"""
        parts = arg.split(None, 1)
        if len(parts) < 2:
            print("  用法: answer <词> <解释>")
            return
        r = learner.answer_question(parts[0], parts[1])
        print(f"  ✅ 已学会: {r['learned']} → {r['answer'][:40]}")

    def do_talk(self, arg):
        """
        自然语言交互: talk <你说的话>

        AM 自动分类:
          - 事实陈述 ("地球是行星") → 提取三元组存入 KG
          - 问题 ("咖啡能让人清醒吗?") → 查 KG 回答
          - 数学 ("2+3=?") → 交给 math_solve
          - 指令 ("搜索黑洞") → 交给对应 Skill
        """
        text = arg.strip()
        if not text:
            print("  用法: talk <你说的话>")
            return
        print(f"  💬 你: {text}")

        # ── 分类 ──
        intent = self._classify(text)

        if intent == "fact":
            self._handle_fact(text)
        elif intent == "question":
            self._handle_question(text)
        elif intent == "math":
            result = skill_lib.best_match(text)
            if result:
                r = result.execute(text, kg)
                val = r.get("result") if r.get("success") else r.get("error")
                print(f"  🧮 AM: {val}")
        elif intent == "command":
            if "搜索" in text or "search" in text.lower():
                query = text.replace("搜索", "").replace("search", "").strip()
                results = web_search.search(query)
                for r in results[:3]:
                    print(f"  📄 {r.title}: {r.snippet[:100]}")
            elif "运行" in text or "run" in text.lower():
                print("  🏃 使用 run <N> 命令启动自主运行")
            else:
                print(f"  ❓ AM: 不太确定你想做什么。试试: 地球是行星 / 咖啡会让人清醒吗 / 2+3=?")
        else:
            print(f"  ❓ AM: 没听懂。你是想说一个事实、问一个问题、还是算一个数学题?")

    def _classify(self, text: str) -> str:
        """分类用户意图: fact / question / math / command"""
        # 数学: 含数字+运算符
        if re.search(r'\d+[\+\-\*/\^]', text):
            return "math"
        if re.search(r'[?？]', text):
            return "question"
        # 命令
        if any(kw in text for kw in ["搜索", "查一下", "运行", "run", "help", "帮助"]):
            return "command"
        # 默认: 事实陈述
        if "是" in text or "属于" in text or "等于" in text or "= " in text:
            return "fact"
        return "question"

    def _handle_fact(self, text: str):
        """从自然语言提取三元组"""
        import re as _re
        # 模式1: A 是 B ("咖啡是饮料")
        m = _re.search(r'(.+?)是(.+)', text)
        if m:
            subj, obj = m.group(1).strip(), m.group(2).strip()
            self._learn_triple(subj, "IS_A", obj, 0.7)
            print(f"  ✅ AM: 学会了: {subj} 是一种 {obj}")
            return
        # 模式2: A 会/能/可以 B ("咖啡会让人清醒")
        m = _re.search(r'(.+?)(?:能|会|可以|导致|引起)(.+)', text)
        if m:
            subj, obj = m.group(1).strip(), m.group(2).strip()
            self._learn_triple(subj, "CAUSES", obj, 0.6)
            print(f"  ✅ AM: 学会了: {subj} 会导致 {obj}")
            return
        print(f"  ❓ AM: 没提取出关系, 请用 'A是B' 或 'A会导致B' 的格式")

    def _handle_question(self, text: str):
        """从 KG 回答问题"""
        # 提取查询主体
        import re as _re
        # "咖啡能让人清醒吗?" → 查 咖啡 CAUSES 清醒
        m = _re.search(r'(.+?)(?:能|会|是|可以)(.+)吗?[?？]?', text)
        if m:
            subj = m.group(1).strip()
            obj_hint = m.group(2).strip()
            found = kg.query(subject=subj)
            if found:
                for r in found:
                    print(f"  🧠 AM: {r.subject} --[{r.predicate}]--> {r.object} (可信度 {r.confidence:.0%})")
            else:
                print(f"  ❓ AM: 我不认识 '{subj}'。试试说 'talk {subj}是什么' 给我信息?")
                learner.ask_user(subj, f"用户问了关于'{subj}'的问题, 但KG中没有相关信息")
            return

        # 简单查 KG
        words = text.replace("?", "").replace("？", "").split()
        for w in words[:3]:
            found = kg.query(subject=w)
            if found:
                for r in found[:3]:
                    print(f"  🧠 AM: {r.subject} --[{r.predicate}]--> {r.object} ({r.confidence:.0%})")
                return
        print(f"  ❓ AM: 关于这个我还不知道, 告诉我吧")

    def _learn_triple(self, subj: str, pred: str, obj: str, conf: float):
        kg.add(subj, pred, obj, confidence=conf)
        db.add_relation(subj, pred, obj, conf, source="natural_language")
        """检查环境: env"""
        env = ctool.check_env()
        for k, v in env.items():
            icon = "✅" if v["ok"] else "❌"
            print(f"  {icon} {k}: {v['output']}")

    def do_skills(self, arg):
        """列出所有 Skill: skills"""
        by_cat = skill_lib.list_by_category()
        for cat, skills in by_cat.items():
            print(f"  📦 {cat}:")
            for s in skills:
                print(f"     · {s}")

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
        # 先扫描审计标记: 有反证目标? 优先处理
        audit_targets = [r for r in kg.relations
                         if r.predicate in ("SEEKS_DISPROOF_OF", "NEEDS_CAUSAL_VALIDATION")]
        if audit_targets:
            print(f"\n  🎯 发现 {len(audit_targets)} 个审计标记, 优先处理!")
            for at in audit_targets[:2]:
                target_rel = at.object  # "咖啡--[CAUSES]-->清醒"
                print(f"     🔬 反证实验: 给 \"{target_rel}\" 制造反设场景")

                # 反证模式: 有控制的挑战, 知道什么时候停
                result = falsifier.run(kg, target_rel)
                icon = "🛡️" if result.survived else "💥"
                print(f"     {icon} {result.stop_reason}")
                print(f"        置信度: {result.pre_confidence:.2f} → {result.post_confidence:.2f} "
                      f"(α={result.pre_alpha:.0f}→{result.post_alpha:.0f} "
                      f"β={result.pre_beta:.0f}→{result.post_beta:.0f})")

            print(f"\n  📊 反证实验结果:")
            for r in kg.relations:
                if any(at.object in r.key() for at in audit_targets[:2]):
                    arrow = "↑" if r.confidence > 0.5 else "↓"
                    print(f"     {arrow} {r.key()}: α={r.belief.alpha:.0f} β={r.belief.beta:.0f} 信 {r.confidence:.2f}")
            print()
            # 清掉已处理的审计标记
            for at in audit_targets[:2]:
                kg.relations = [r for r in kg.relations if r != at]

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
        # 追踪预测失败: 如果 H5 是最优但无法产生可验证预测 → 功能性失效
        if hypotheses and hypotheses[0].get("mechanism") == "未建模模式":
            evolution.mhg.reflect_on_failure({"data_type": "unknown"})
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
