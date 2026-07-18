"""
Portal — HiveMind 2.4 统一 I/O 层

入口: 系统主动拉取数据（好奇心驱动），不是被动接收。
出口: 决策、表达、告警统一管道。

核心概念:
- 数据源不只是"被读的 CSV"，而是系统主动查询的端点
- Poll 由好奇心触发——系统决定何时看，不是外部推
- 出口不只有决策数字，还包括 Learner 的语音、Mother 的推理、Guard 的告警
"""
import time
import logging
from abc import ABC, abstractmethod
from typing import Optional, Callable, Dict, Any
from dataclasses import dataclass, field

logger = logging.getLogger("hivemind_v2.portal")


# ──────────── 数据源抽象 ────────────

class DataSource(ABC):
    """可被系统主动查询的数据源"""

    @abstractmethod
    def poll(self) -> Optional[float]:
        """
        系统主动调用: "有新的数据吗？"
        返回 None = 暂无新数据，返回 float = 有新观测值
        """
        ...

    @abstractmethod
    def has_more(self) -> bool:
        """数据源是否还有更多数据"""
        ...

    @property
    @abstractmethod
    def name(self) -> str:
        ...


class CSVSource(DataSource):
    """CSV 文件数据源 — 逐行轮询"""
    def __init__(self, path: str, loop: bool = True):
        self._path = path
        self._loop = loop
        self._values = []
        self._cursor = 0
        self._load()

    def _load(self):
        import csv
        with open(self._path, 'r') as f:
            reader = csv.DictReader(f)
            self._values = [float(list(r.values())[0]) for r in reader]

    def poll(self) -> Optional[float]:
        if self._cursor >= len(self._values):
            if self._loop:
                self._cursor = 0
            else:
                return None
        val = self._values[self._cursor]
        self._cursor += 1
        return val

    def has_more(self) -> bool:
        return self._cursor < len(self._values) or self._loop

    @property
    def name(self) -> str:
        return f"CSV({self._path})"


class LiveSource(DataSource):
    """
    实时数据源 — 外部代码通过 push() 写入
    适合对接 WebSocket/MQTT/API 回调
    """
    def __init__(self, max_buffer: int = 1000):
        self._buffer = []
        self._max_buffer = max_buffer
        self._stopped = False

    def push(self, value: float):
        """外部调用: 把新数据推入缓冲区"""
        self._buffer.append(value)
        if len(self._buffer) > self._max_buffer:
            self._buffer = self._buffer[-self._max_buffer:]

    def poll(self) -> Optional[float]:
        if self._buffer:
            return self._buffer.pop(0)
        return None

    def stop(self):
        self._stopped = True

    def has_more(self) -> bool:
        return not self._stopped or len(self._buffer) > 0

    @property
    def name(self) -> str:
        return "LiveSource"


# ──────────── 出口 ────────────

@dataclass
class Emission:
    """一次系统输出"""
    timestamp: float
    type: str  # "decision" | "expression" | "alert" | "status"
    content: Dict[str, Any]


class OutputSink(ABC):
    """输出目标抽象"""
    @abstractmethod
    def emit(self, emission: Emission):
        ...


class ConsoleSink(OutputSink):
    """控制台输出"""
    def emit(self, e: Emission):
        ts = time.strftime("%H:%M:%S", time.localtime(e.timestamp))
        if e.type == "decision":
            c = e.content
            print(f"[{ts}] 🧠 决策: {c.get('consensus', 0):.2f} "
                  f"({c.get('confidence', 0):.0%}) — {c.get('reasoning', '')[:60]}")
        elif e.type == "alert":
            print(f"[{ts}] ⚠️  {e.content.get('message', '')}")
        elif e.type == "status":
            print(f"[{ts}] 📊 {e.content.get('message', '')}")
        elif e.type == "expression":
            print(f"[{ts}] 💬 [{e.content.get('learner', '?')}] {e.content.get('text', '')}")
        elif e.type == "search":
            print(f"[{ts}] 🔍 自主搜索: '{e.content.get('query', '?')}'")


class LogSink(OutputSink):
    """日志文件输出"""
    def __init__(self, path: str):
        self._path = path
        self._buffer = []

    def emit(self, e: Emission):
        import json
        self._buffer.append({
            "timestamp": e.timestamp,
            "type": e.type,
            "content": e.content,
        })

    def flush(self):
        import json
        with open(self._path, 'w') as f:
            json.dump(self._buffer, f, indent=2, ensure_ascii=False)
        self._buffer = []


# ──────────── 好奇心引擎 ────────────

class CuriosityEngine:
    """
    决定系统何时主动拉取数据。

    四个触发条件:
    1. 数据陈旧 — 超过 N 秒没新数据
    2. 置信度低 — 共识不够确定
    3. Learner 请求 — 某 Learner 高度不确定
    4. 知识缺口 — 连续 N 轮低置信 → "我需要搜索新信息"
    """

    def __init__(
        self,
        stale_threshold: float = 5.0,
        confidence_low: float = 0.5,
        max_poll_interval: float = 0.1,
        knowledge_gap_rounds: int = 3,
        exploration_patience: int = 15,   # v2.10: 结构断层后冷却轮数
    ):
        self.stale_threshold = stale_threshold
        self.confidence_low = confidence_low
        self.max_poll_interval = max_poll_interval
        self.knowledge_gap_rounds = knowledge_gap_rounds
        self.exploration_patience = exploration_patience
        self.last_poll_time = 0.0
        self._low_confidence_streak = 0
        self._last_search_query = ""
        self.search_count = 0
        self._gap_cooldown = 0           # 结构断层冷却
        self._experiment_interval = 30   # 定期实验好奇
        self._experiment_rounds = 0

    def should_poll(
        self,
        last_decision_confidence: float,
        learners,
        seconds_since_last_data: float,
        function_learner=None,  # v2.8: FunctionLearner for structure_gap
    ) -> tuple:
        now = time.time()

        # 条件4: 知识缺口 — streak计数独立于防抖
        if last_decision_confidence > 0 and last_decision_confidence < self.confidence_low:
            self._low_confidence_streak += 1
        else:
            self._low_confidence_streak = 0

        if self._low_confidence_streak >= self.knowledge_gap_rounds:
            self._low_confidence_streak = 0
            self.search_count += 1
            self.last_poll_time = now
            return "search", f"知识缺口 (连续{self.knowledge_gap_rounds}轮低置信)"

        # 条件5: 结构断层 (有耐心)
        self._gap_cooldown += 1
        if function_learner is not None and function_learner.structure_gap():
            if self._gap_cooldown >= self.exploration_patience:
                self._gap_cooldown = 0
                self.search_count += 1
                self.last_poll_time = now
                return "search", "结构断层 (触发探索实验)"

        # 条件6: 定期实验好奇 (v2.10)
        self._experiment_rounds += 1
        if self._experiment_rounds >= self._experiment_interval:
            self._experiment_rounds = 0
            self.search_count += 1
            self.last_poll_time = now
            return "experiment", "定期实验 (检验当前假设是否最优)"

        # 防抖 (搜索优先于防抖)
        if now - self.last_poll_time < self.max_poll_interval:
            return False, ""

        # 条件1: 数据陈旧
        if seconds_since_last_data > self.stale_threshold:
            self.last_poll_time = now
            return True, f"数据陈旧 ({seconds_since_last_data:.0f}s 无新数据)"

        # 条件2: 置信度低
        if last_decision_confidence < self.confidence_low and last_decision_confidence > 0:
            self.last_poll_time = now
            return True, f"置信度低 ({last_decision_confidence:.2f})"

        # 条件3: Learner 请求
        for l in learners:
            sigma = l.belief.sigma
            if sigma > 15.0:
                self.last_poll_time = now
                return True, f"{l.learner_id} 高度不确定 (σ={sigma:.1f})"

        return False, ""


class SearchDataSource(DataSource):
    """
    搜索数据源 — 每次 poll() 触发一次 WebSearch。

    不直接执行搜索（WebSearch 是 Agent 工具），而是:
    1. 设置 pending_query
    2. 外部通过 push_result() 推送解析后的数值
    3. poll() 返回缓冲区中的值
    """

    def __init__(self, max_buffer: int = 50):
        self._buffer = []
        self._max_buffer = max_buffer
        self.pending_query: str | None = None

    def set_query(self, query: str):
        """设置待搜索的问题——外部监听这个字段执行 WebSearch"""
        self.pending_query = query

    def push_result(self, value: float):
        """外部调用: 推送搜索结果中的数值"""
        self._buffer.append(value)
        if len(self._buffer) > self._max_buffer:
            self._buffer = self._buffer[-self._max_buffer:]

    def poll(self) -> float | None:
        if self._buffer:
            return self._buffer.pop(0)
        return None

    def has_more(self) -> bool:
        return True  # 搜索源永远可用

    @property
    def name(self) -> str:
        return "SearchDataSource"


# ──────────── Portal — 统一入口 ────────────

class Portal:
    """
    HiveMind 的"眼睛、耳朵、嘴巴"。

    输入: DataSource (系统主动 poll)
    输出: OutputSink (决策/表达/告警)
    节奏: CuriosityEngine (系统决定何时拉数据)
    """

    def __init__(
        self,
        source: DataSource,
        sinks: list = None,
        curiosity: CuriosityEngine = None,
    ):
        self.source = source
        self.sinks = sinks or [ConsoleSink()]
        self.curiosity = curiosity or CuriosityEngine()

        self.total_polls = 0
        self.total_emissions = 0
        self.last_data_time = 0.0
        self.running = True

    def poll(self) -> Optional[float]:
        """主动拉取一个数据点"""
        val = self.source.poll()
        if val is not None:
            self.last_data_time = time.time()
            self.total_polls += 1
        return val

    def emit(self, emission: Emission):
        """输出到所有出口"""
        for sink in self.sinks:
            sink.emit(emission)
        self.total_emissions += 1

    def emit_decision(self, decision):
        """快捷方法: 输出一条决策"""
        self.emit(Emission(
            timestamp=time.time(),
            type="decision",
            content={
                "consensus": decision.consensus,
                "confidence": decision.confidence,
                "reasoning": decision.reasoning,
                "primary_influence": decision.primary_influence,
                "dissenting_view": decision.dissenting_view,
            }
        ))

    def emit_alert(self, message: str):
        self.emit(Emission(
            timestamp=time.time(),
            type="alert",
            content={"message": message}
        ))

    def emit_expression(self, learner_id: str, text: str):
        self.emit(Emission(
            timestamp=time.time(),
            type="expression",
            content={"learner": learner_id, "text": text}
        ))

    def emit_search(self, query: str):
        """v2.7: 发射搜索请求"""
        self.emit(Emission(
            timestamp=time.time(),
            type="search",
            content={"query": query}
        ))

    def emit_status(self, message: str):
        self.emit(Emission(
            timestamp=time.time(),
            type="status",
            content={"message": message}
        ))

    def seconds_since_last_data(self) -> float:
        if self.last_data_time == 0:
            return float("inf")
        return time.time() - self.last_data_time

    def stop(self):
        self.running = False
