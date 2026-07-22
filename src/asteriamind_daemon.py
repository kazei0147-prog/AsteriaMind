"""
AsteriaMind Daemon — 常驻认知守护进程 (AsteriaMind v3.2)

不是一次性脚本。是一个活着的认知进程:
  - 主事件循环 (CognitiveScheduler 决定下一步)
  - 自动状态快照 (崩溃可恢复)
  - 认知心跳 (每小时反思, 每天回顾)
  - 信号安全退出 (SIGTERM/SIGINT → 保存 → 退出)

运行方式:
  python asteriamind_daemon.py                     # 前台运行
  python asteriamind_daemon.py --kg kg_main.json    # 从快照恢复
  nohup python asteriamind_daemon.py &              # 后台运行
"""
import signal, sys, time, os, json, math, random
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional, Callable

# ── 导入 AM 核心 ──
sys.path.insert(0, str(Path(__file__).parent))
from AsteriaMind.knowledge import KnowledgeGraph
from AsteriaMind.hypothesis_template import (
    HypothesisEngine, TemplateRegistry, TheoryGovernance, _builtin_templates,
)
from AsteriaMind.cognitive_evolution import CognitiveEvolutionLayer
from AsteriaMind.certainty_audit import CertaintyAudit
from AsteriaMind.falsification import (
    FalsificationController, WebSearchInterface, SourceAuthorityTracker,
)
from AsteriaMind.vector_layer import VectorLayer
from AsteriaMind.cross_layer import CrossLayerBridge
from AsteriaMind.human_review import HumanReviewInterface, ProvenanceGuard
from AsteriaMind.knowledge_request import (
    KnowledgeRequestMonitor, KnowledgeAcquisitionExecutor,
)
from AsteriaMind.math_reasoner import MathReasoner


@dataclass
class DaemonState:
    """守护进程的完整状态——可快照, 可恢复"""
    kg_json: str = ""         # KG 的 JSON 快照
    template_count: int = 0
    round_count: int = 0
    uptime_seconds: float = 0.0
    last_snapshot: float = 0.0
    events_processed: int = 0
    searches_done: int = 0
    audits_done: int = 0
    evolutions: int = 0


class CognitiveScheduler:
    """
    认知调度器: 决定 AM 现在该干什么。

    不拍脑袋, 不固定节拍——根据认知状态、队列、失败统计来决定:
      - 有紧急知识请求? → 搜索
      - 有高置信度无反证信念? → 审计
      - 有新向量? → 桥接
      - 距上次治理 >= 10min? → 治理+演化
      - 什么都没? → 轻度探索或休眠
    """

    def __init__(self, kg, engine, auditor, falsifier, bridge, governance,
                 evolution, krm, kae, vl, knowledge_queue):
        self.kg = kg
        self.engine = engine
        self.auditor = auditor
        self.falsifier = falsifier
        self.bridge = bridge
        self.governance = governance
        self.evolution = evolution
        self.krm = krm
        self.kae = kae
        self.vl = vl
        self.queue = knowledge_queue

        # 上次调用时间
        self.last: dict[str, float] = {
            "search": 0, "audit": 0, "bridge": 0, "govern": 0, "heartbeat": 0,
        }
        self.vec_since_bridge = 0
        self.start_time = time.time()

    def decide_and_execute(self) -> Optional[str]:
        """决定并执行下一步。返回动作名称或 None。"""
        now = time.time()

        # ── 优先级 1: 紧急知识请求 ──
        if self.queue:
            urgent = any(
                hasattr(r, 'urgency') and r.urgency > 0.5 for r in self.queue
            )
            if urgent and now - self.last["search"] > 5:
                requests = self.krm.scan(self.kg)
                if requests:
                    result = self.kae.execute_batch(max_requests=2)
                    self.last["search"] = now
                    if result["new_relations"]:
                        self.vec_since_bridge += result["new_relations"]
                    return "search"

        # ── 优先级 2: 认知演化 (MH 检测) ──
        if now - self.last["govern"] > 60 and self.kg.relations:
            goals = self.kg.generate_goals(max_goals=2)
            all_hyps = []
            for g in goals[:2]:
                hyps = self.engine.generate(self.kg, g["target"], g["type"])
                all_hyps.extend(hyps)
            if all_hyps:
                evo = self.evolution.observe_and_evolve(goals, all_hyps, self.kg, 0)
                self.last["govern"] = now
                if evo.get("alert") == "meta_hypothesis_generated":
                    return "evolution"

        # ── 优先级 3: 审计 ──
        if now - self.last["audit"] > 30 and self.kg.relations:
            risky = [f for f in self.auditor.audit(self.kg)
                     if f.risk_level in ("medium", "high")]
            if risky:
                self.falsifier.run(self.kg, risky[0].relation_key, max_rounds=3)
                self.last["audit"] = now
                return "audit"

        # ── 优先级 4: 桥接 ──
        if self.vec_since_bridge >= 3 and now - self.last["bridge"] > 45:
            self.bridge.discover()
            self.vec_since_bridge = 0
            self.last["bridge"] = now
            return "bridge"

        # ── 优先级 5: 认知心跳 ──
        if now - self.last["heartbeat"] > 600:  # 每 10 分钟
            self._cognitive_heartbeat()
            self.last["heartbeat"] = now
            return "heartbeat"

        # ── 默认: 轻度探索 ──
        if self.kg.relations:
            goals = self.kg.generate_goals(max_goals=1)
            if goals:
                hyps = self.kg.generate_competing_hypotheses(
                    goals[0]["target"], goals[0]["type"]
                )
                if hyps:
                    return "explore"

        return None

    def _cognitive_heartbeat(self):
        """认知心跳: 定期自我反思, 不需要外部事件"""
        elapsed = time.time() - self.start_time

        # 每小时: 治理审查
        if int(elapsed) % 3600 < 60:
            self.governance.review(int(elapsed))

        # 每天: 深层反思 (简化为统计)
        if int(elapsed) % 86400 < 60 and self.kg.relations:
            total = len(self.kg.relations)
            strong = sum(1 for r in self.kg.relations if r.confidence > 0.8)
            weak = sum(1 for r in self.kg.relations if r.confidence < 0.4)
            print(f"  💓 认知心跳 [{int(elapsed/3600)}h]: "
                  f"KG:{total} 强信念:{strong} 弱信念:{weak}")


class AsteriaDaemon:
    """
    AsteriaMind 守护进程——她活着的形态。

    不是等命令。是自己决定下一步该做什么。
    """

    def __init__(self, kg_path: str = None):
        self.running = True
        self.start_time = time.time()

        # ── 加载或初始化 KG ──
        if kg_path and Path(kg_path).exists():
            print(f"[AsteriaDaemon] 从快照恢复: {kg_path}")
            self.kg = KnowledgeGraph.load(kg_path)
        else:
            self.kg = KnowledgeGraph()
            print("[AsteriaDaemon] 新 KG 初始化")

        # ── 初始化所有模块 ──
        self.tmpl_registry = TemplateRegistry()
        for t in _builtin_templates():
            self.tmpl_registry.register(t)
        self.engine = HypothesisEngine(self.tmpl_registry)
        self.vl = VectorLayer(dim=128)
        self.governance = TheoryGovernance(self.tmpl_registry)
        self.auditor = CertaintyAudit()
        self.falsifier = FalsificationController()
        self.bridge = CrossLayerBridge(self.kg, self.vl)
        self.evolution = CognitiveEvolutionLayer(self.tmpl_registry, self.kg)

        self.knowledge_queue = []
        self.web_search = WebSearchInterface()
        self.krm = KnowledgeRequestMonitor(self.knowledge_queue)
        self.kae = KnowledgeAcquisitionExecutor(
            self.knowledge_queue, self.web_search, self.kg, self.vl
        )

        self.scheduler = CognitiveScheduler(
            self.kg, self.engine, self.auditor, self.falsifier,
            self.bridge, self.governance, self.evolution,
            self.krm, self.kae, self.vl, self.knowledge_queue,
        )

        # ── 信号处理 ──
        signal.signal(signal.SIGTERM, self._shutdown)
        signal.signal(signal.SIGINT, self._shutdown)

        # ── 状态 ──
        self.state = DaemonState()
        self.state.template_count = len(self.tmpl_registry.templates)

        # 初始索引
        if self.kg.relations:
            self.vl.batch_index(self.kg.relations)

    def _shutdown(self, *_):
        print(f"\n[AsteriaDaemon] 收到终止信号...")
        self.running = False

    def run(self):
        """主事件循环"""
        print(f"[AsteriaDaemon] 启动 PID={os.getpid()} "
              f"KG:{len(self.kg.relations)}关系 "
              f"模板:{self.state.template_count}个")
        print(f"[AsteriaDaemon] Ctrl+C 优雅退出\n")

        tick_interval = 0.5  # 秒

        while self.running:
            action = self.scheduler.decide_and_execute()

            if action:
                self.state.events_processed += 1
                if action == "search":
                    self.state.searches_done += 1
                elif action == "audit":
                    self.state.audits_done += 1
                elif action == "evolution":
                    self.state.evolutions += 1
                elif action == "heartbeat":
                    pass  # heartbeat 有自己的打印

            # 定期快照
            now = time.time()
            if now - self.state.last_snapshot > 300:  # 每 5 分钟
                self._snapshot()
                self.state.last_snapshot = now

            time.sleep(tick_interval)

        # 退出前保存
        self._snapshot()
        self._print_stats()

    def _snapshot(self):
        """保存完整状态快照"""
        path = Path("kg_snapshot_latest.json")
        self.kg.save(str(path))
        self.state.kg_json = path.name
        self.state.round_count = int(time.time() - self.start_time)
        self.state.uptime_seconds = time.time() - self.start_time

    def _print_stats(self):
        elapsed = time.time() - self.start_time
        h = int(elapsed / 3600)
        m = int((elapsed % 3600) / 60)
        print(f"\n[AsteriaDaemon] 退出。运行 {h}h{m}m, "
              f"处理 {self.state.events_processed} 事件 "
              f"(搜索:{self.state.searches_done} 审计:{self.state.audits_done} "
              f"演化:{self.state.evolutions})")
        print(f"[AsteriaDaemon] 快照已保存 → kg_snapshot_latest.json")


# ── 入口 ──

if __name__ == "__main__":
    kg_path = None
    args = sys.argv[1:]
    for i, arg in enumerate(args):
        if arg == "--kg" and i + 1 < len(args):
            kg_path = args[i + 1]
        elif arg == "--help":
            print("用法: python asteriamind_daemon.py [--kg kg_snapshot.json]")
            print("  --kg PATH  从快照恢复 KG")
            print("  Ctrl+C     优雅退出 (自动保存)")
            sys.exit(0)

    daemon = AsteriaDaemon(kg_path)
    daemon.run()
