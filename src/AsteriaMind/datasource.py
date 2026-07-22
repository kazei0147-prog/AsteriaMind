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


# ═══════════════════ IA + KA: 文本 → 主张 → 同化 ═══════════════════

import re

@dataclass
class Claim:
    """从文本中提取的一条主张 (不是事实, 是可质疑的假说)"""
    subject: str
    predicate: str
    object: str
    raw_text: str
    source_name: str = ""
    source_credibility: float = 0.5
    claim_confidence: float = 0.3  # 初始信任: 低! 等验证


class TextIngestor:
    """
    信息获取层: 自由文本 → 结构化主张。

    不做传统 NLP (分词/命名实体/依存句法)。
    做的是: 识别文本中的"谁说了什么关于什么"。
    每条输出是一个 Claim ——进入同化管道, 而非直接入库。
    """

    # 关系词映射: 文本中常见的动词 → KG 中的 predicate
    RELATION_PATTERNS = [
        ("导致|引起|造成|引发|促使", "CAUSES"),
        ("属于|是一种|是.*的一种|归类为", "IS_A"),
        ("具有|拥有|带有|包含|含有", "HAS"),
        ("预测|预示|预兆|意味着|意味", "PREDICTS"),
        ("依赖|取决于|依靠", "DEPENDS_ON"),
        ("触发|激活|启动|开启", "TRIGGERS"),
        ("与.*相关|关联|联系|有关", "CORRELATED_WITH"),
        ("响应|反应|对.*作出", "RESPONDS_TO"),
    ]

    def __init__(self):
        self._compiled = [(re.compile(p), pred) for p, pred in self.RELATION_PATTERNS]

    def ingest(self, text: str, source_name: str = "text",
               source_credibility: float = 0.5) -> list[Claim]:
        """
        从一段文本中提取所有主张。

        每句话按"主语 动词 宾语"的简单模式识别。
        不保证正确——但每条主张以低置信度进入同化管道。
        """
        claims = []
        sentences = re.split(r'[。.!！?？\n]+', text)

        for sent in sentences:
            sent = sent.strip()
            if len(sent) < 4:
                continue

            for pattern, predicate in self._compiled:
                m = pattern.search(sent)
                if m:
                    # 主语: 动词前面的部分
                    subject = sent[:m.start()].strip()
                    # 宾语: 动词后面的部分
                    obj = sent[m.end():].strip()

                    # 清理
                    subject = re.sub(r'^(的|了|已经|正在|可以|可能|应该|会|将|不|没|没有)\s*', '', subject)
                    obj = re.sub(r'^(的|了|已经|正在|可以|可能|应该|会|将)\s*', '', obj)

                    if subject and obj and len(subject) < 50 and len(obj) < 50:
                        # 否定处理
                        neg_match = re.search(r'(不|没|没有|非|并非)\s*', sent[:m.start()])
                        if neg_match:
                            predicate = "NOT_" + predicate
                            # 从主语中移除否定词
                            subject = re.sub(r'(不|没|没有|非|并非)\s*$', '', subject).strip()

                        claims.append(Claim(
                            subject=subject, predicate=predicate, object=obj,
                            raw_text=sent,
                            source_name=source_name,
                            source_credibility=source_credibility,
                            claim_confidence=source_credibility * 0.3,  # 初始最大 0.3
                        ))
                        break  # 一句话只匹配第一个模式

        return claims


class KnowledgeAssimilator:
    """
    知识同化层: 主张 → 与已有知识碰撞 → 接受/拒绝/待验证。

    这是 IA+KA 的核心: 不是"存事实", 是"同化主张"。
    利用已有的 KG 竞争假说 + 奥卡姆剃刀 + 主动拒绝机制。
    """

    def __init__(self, kg, pipeline: DataPipeline = None):
        self.kg = kg
        self.pipeline = pipeline
        self.assimilation_log: list[dict] = []

    def assimilate(self, claims: list[Claim]) -> dict:
        """
        将一批主张同化到知识图谱中。

        每个主张经历:
          1. 检查是否有冲突 (已有信念 vs 新主张)
          2. 无冲突 → 以低置信度加入 (source="claimed")
          3. 有冲突 → 调用已有冲突处理协议
          4. 如果置信度极低 → 进入奥卡姆竞技场
        """
        results = {"accepted": 0, "conflicted": 0, "rejected": 0, "details": []}

        for claim in claims:
            existing = self.kg.query(claim.subject, claim.predicate)

            # 跨谓词冲突: NOT_CAUSES vs CAUSES, NOT_IS_A vs IS_A 等
            if not existing and claim.predicate.startswith("NOT_"):
                base_pred = claim.predicate[4:]
                existing = self.kg.query(claim.subject, base_pred)

            action = "accepted"

            if existing:
                best = existing[0]
                # 跨谓词冲突: claim 说 NOT_X, 已有说 X → 同一主语宾语 → 真冲突
                cross_negation = (claim.predicate.startswith("NOT_") and
                                  claim.predicate[4:] == best.predicate and
                                  claim.object == best.object)

                # 冲突检测
                is_conflict = ((best.object != claim.object and best.confidence > 0.4)
                               or cross_negation)
                if is_conflict:
                    # 如果已有信念很稳固, 降低主张权重; 反之进入竞技场
                    if best.confidence > 0.85 and best.belief.evidence_total > 20:
                        # 内核信念 — 需要大量证据才能挑战
                        self.kg.observe(best.subject, best.predicate, best.object,
                                        correct=True, weight=0.1,
                                        context=f"外部文本主张'{claim.object}'被驳回")
                        action = "rejected"
                        results["rejected"] += 1
                        results["details"].append({
                            "claim": f"{claim.subject} {claim.predicate} {claim.object}",
                            "action": "rejected",
                            "reason": f"与稳固信念冲突 (置信度 {best.confidence:.2f})",
                        })
                    else:
                        # 信念还不够稳 — 走冲突处理协议
                        if self.pipeline:
                            dp = DataPoint(
                                source="text", raw_text=claim.raw_text,
                                subject=claim.subject, predicate=claim.predicate,
                                object=claim.object, confidence=claim.claim_confidence,
                            )
                            self.pipeline._handle_conflict(dp, best)
                        action = "conflicted"
                        results["conflicted"] += 1
                        results["details"].append({
                            "claim": f"{claim.subject} {claim.predicate} {claim.object}",
                            "action": "conflicted",
                            "reason": f"与已有信念冲突 (已有: {best.object}, 置信度 {best.confidence:.2f})",
                        })
                    continue

                # 同方向主张: 已有 → 强化
                if best.object == claim.object:
                    self.kg.observe(best.subject, best.predicate, best.object,
                                    correct=True, weight=claim.claim_confidence,
                                    context=f"来源: {claim.source_name}")
                    results["accepted"] += 1
                    results["details"].append({
                        "claim": f"{claim.subject} {claim.predicate} {claim.object}",
                        "action": "reinforced",
                        "reason": f"支持已有信念 (置信度 {best.confidence:.2f}→)",
                    })
                    continue

            # 全新主张: 以低置信度加入, 标记为 claimed
            self.kg.add(claim.subject, claim.predicate, claim.object,
                        confidence=claim.claim_confidence, source="claimed")
            results["accepted"] += 1
            results["details"].append({
                "claim": f"{claim.subject} {claim.predicate} {claim.object}",
                "action": "accepted",
                "reason": f"新主张, 置信度 {claim.claim_confidence:.2f} (来自 {claim.source_name})",
            })

        self.assimilation_log.append(results)
        return results
