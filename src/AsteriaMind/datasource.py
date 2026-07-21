"""
DataSource — AsteriaMind 的外部世界接口 (v3.0)

不是 LLM 搜索——是 AM 自己决定查什么、查回来怎么想、怎么存。

三种数据源:
  LibrarySource  — 模拟"知识库", 包含已知事实
  APISource      — 调用外部 API (可联网)
  Observational  — 观测世界 (当前 demo 用的 world() 函数)

查询流:
  Curiosity 触发 → MotherMind 生成 query → DataSource.fetch(query)
  → 文本解析 → 概念抽取 → 存入 KnowledgeGraph
"""
from dataclasses import dataclass
from typing import List, Optional, Callable
import random


@dataclass
class DataPoint:
    """从外部世界获取的一条信息"""
    source: str
    raw_text: str
    subject: str = ""
    predicate: str = ""
    object: str = ""
    confidence: float = 0.5

    def to_triple(self) -> tuple:
        return (self.subject, self.predicate, self.object, self.confidence)


class LibrarySource:
    """
    模拟知识库——像一个"可查询的外部数据库"。

    当 AM 问"物体C 还跟什么有关系?"时,
    它返回已知但 AM 还没学过的事实。
    """

    def __init__(self):
        self._facts: dict[str, list[tuple]] = {}  # entity → [(predicate, object, conf)]

    def add_fact(self, subject: str, predicate: str, object: str,
                 confidence: float = 0.7):
        self._facts.setdefault(subject, []).append((predicate, object, confidence))

    def query(self, subject: str) -> list[DataPoint]:
        """查一个实体: 返回所有已知事实"""
        facts = self._facts.get(subject, [])
        results = []
        for pred, obj, conf in facts:
            results.append(DataPoint(
                source="library",
                raw_text=f"{subject} {pred} {obj}",
                subject=subject, predicate=pred, object=obj,
                confidence=conf,
            ))
        # 也查关系另一端 (object 作为 subject)
        for entity, facts_list in self._facts.items():
            for pred, obj, conf in facts_list:
                if obj == subject:
                    results.append(DataPoint(
                        source="library",
                        raw_text=f"{entity} {pred} {subject}",
                        subject=entity, predicate=pred, object=subject,
                        confidence=conf,
                    ))
        return results

    def search(self, keyword: str) -> list[DataPoint]:
        """模糊查: 返回所有包含关键词的事实"""
        results = []
        for entity, facts_list in self._facts.items():
            if keyword in entity:
                results.extend(self.query(entity))
            for pred, obj, conf in facts_list:
                if keyword in pred or keyword in obj:
                    results.append(DataPoint(
                        source="library",
                        raw_text=f"{entity} {pred} {obj}",
                        subject=entity, predicate=pred, object=obj,
                        confidence=conf,
                    ))
        return results


class DataPipeline:
    """
    数据摄入管道:
      外部数据 → 概念抽取 → 关系建立 → 知识图谱存储

    解决了"数据来了怎么变成知识"的问题。
    """

    def __init__(self, kg, library: LibrarySource = None):
        self.kg = kg
        self.library = library
        self.fetch_count = 0
        self.fetch_log: list[dict] = []

    def fetch_and_learn(self, subject: str) -> list[DataPoint]:
        """
        AM 自主查询: "我不懂 X, 去查一下"
        返回学到的新知识。
        """
        if self.library is None:
            return []

        results = self.library.query(subject)
        if not results:
            # 没有精确匹配, 试试模糊搜索
            results = self.library.search(subject)

        learned = []
        for r in results:
            existing = self.kg.query(r.subject, r.predicate)

            if existing:
                best = existing[0]

                # ── 冲突检测 ──
                if best.object != r.object and best.confidence > 0.4:
                    self._handle_conflict(r, best)
                    learned.append(r)
                    continue

                # 同方向但外部置信度低 → 拒绝
                if best.object == r.object and r.confidence <= best.confidence * 0.8:
                    self.fetch_count += 1
                    self.fetch_log.append({
                        "subject": subject, "action": "rejected",
                        "reason": f"外部({r.confidence}) ≪ 内部({best.confidence:.2f})",
                    })
                    continue

            self.kg.add(r.subject, r.predicate, r.object,
                        confidence=r.confidence, source="external")
            learned.append(r)
            self.fetch_count += 1

    def _handle_conflict(self, external: DataPoint, internal):
        """
        冲突处理: 不覆盖, 不平均 — 放入 KG 作为竞争假说等验证。

        H_ext: 外部信息正确
        H_int: 已有模型正确
        H_hidden: 存在隐藏条件 (两者在不同语境下都对)
        """
        conf = {
            "H_ext": external.confidence,
            "H_int": internal.confidence,
            "H_hidden": max(0.1, 1.0 - abs(external.confidence - internal.confidence)),
        }
        conflict_key = f"冲突:{external.subject}:{external.predicate}"
        self.kg.add(external.subject, external.predicate, external.object,
                    confidence=external.confidence * 0.3, source="unverified_external")
        self.kg.add(conflict_key, "HAS_ALTERNATIVE", external.object,
                    confidence=conf["H_ext"], source="conflict")
        self.kg.add(conflict_key, "HAS_ALTERNATIVE", internal.object,
                    confidence=conf["H_int"], source="conflict")
        self.fetch_log.append({
            "subject": external.subject, "action": "conflict",
            "external": f"{external.subject} {external.predicate} {external.object}",
            "internal": f"{internal.subject} {internal.predicate} {internal.object} ({internal.confidence:.2f})",
            "h_ext": conf["H_ext"], "h_int": conf["H_int"], "h_hidden": conf["H_hidden"],
        })

    def explore_entity(self, subject: str) -> str:
        """
        完整流程: 查询 → 学习 → 报告
        返回自然语言摘要。
        """
        learned = self.fetch_and_learn(subject)
        if not learned:
            return f"关于\"{subject}\"没有在外部知识库中找到新知识。"

        summary = f"关于\"{subject}\"学到了 {len(learned)} 条新知识:\n"
        for r in learned[:5]:
            summary += f"  {r.subject} {r.predicate} {r.object} (置信度 {r.confidence})\n"
        if len(learned) > 5:
            summary += f"  ...等 {len(learned)} 条"
        return summary
