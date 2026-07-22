"""
KnowledgeRequestMonitor + KnowledgeAcquisitionExecutor (AsteriaMind v3.2)

单一职责:
  Monitor: 只扫描缺口, 只发采购申请。不推理, 不消化, 不改信念。
  Executor: 只取采购申请, 只执行搜索+同化。不管该不该搜, 只管搜了怎么存。

连接方式: 共享请求队列 (list), Monitor 往里放, Executor 往里取。
其他模块也可以往队列里放请求 (比如 MotherMind 说"我需要 XXX 的证据")。
"""
import time
from dataclasses import dataclass, field


@dataclass
class KnowledgeRequest:
    """一条知识采购申请——不是知识, 是"我需要知识"的声明"""
    query: str
    urgency: float          # 0.0~1.0, 越高越紧急
    context: str            # 为什么需要这条知识
    constraints: list[str]  # ["需可证伪", "需来源可追溯"]
    posted_by: str          # 哪个模块发的
    timestamp: float = field(default_factory=time.time)


class KnowledgeRequestMonitor:
    """
    知识缺口监控器——单一职责: 发现缺口, 发采购单。

    不执行搜索、不同化、不更新信念、不生成假说。
    只干一件事: 扫描 KG → 发现结构性缺口 → POST 请求到队列。
    """

    def __init__(self, queue: list = None):
        self.queue = queue or []
        self.scan_count = 0

    def scan(self, kg) -> list[KnowledgeRequest]:
        """
        扫描 KG, 找到需要新知识的缺口。

        三种触发:
          1. 低 α/β 比: 信念太弱, 需要更多证据
          2. 无反证的高置信度信念: 可能需要反向验证
          3. 模板无法覆盖的现象 (残差)
        """
        requests = []

        for r in kg.relations:
            ratio = r.belief.alpha / max(0.1, r.belief.beta)

            # 触发1: 信念太弱 (证据不足)
            if ratio < 2.0 and r.belief.evidence_total < 10:
                requests.append(KnowledgeRequest(
                    query=f"{r.subject} {r.predicate} {r.object}",
                    urgency=0.7,
                    context=f"α={r.belief.alpha:.1f} β={r.belief.beta:.1f} 证据不足, 需要外部验证",
                    constraints=["需可证伪", "需来源可追溯", "优先高质量来源"],
                    posted_by="KnowledgeRequestMonitor::weak_belief",
                ))

            # 触发2: 无反证的高置信度 (缺批判性验证)
            if r.confidence > 0.85 and len(r.counter_evidence) == 0:
                requests.append(KnowledgeRequest(
                    query=f"{r.subject} {r.predicate} {r.object} 反驳证据",
                    urgency=0.5,
                    context=f"高置信度但从未被质疑, 需主动寻找反证",
                    constraints=["需可证伪", "找反面证据, 非支持证据"],
                    posted_by="KnowledgeRequestMonitor::no_counter_evidence",
                ))

        # 去重: 同 query 只保留 urgency 最高的
        seen = {}
        for req in requests:
            if req.query not in seen or req.urgency > seen[req.query].urgency:
                seen[req.query] = req

        for req in seen.values():
            self.queue.append(req)

        self.scan_count += 1
        return list(seen.values())


class KnowledgeAcquisitionExecutor:
    """
    知识获取执行器——单一职责: 取采购单, 执行搜索, 同化入库。

    不管该不该搜, 不管搜什么——只管搜了之后怎么存。
    """

    def __init__(self, queue: list = None, web_search=None, kg=None, vl=None):
        self.queue = queue or []
        self.web_search = web_search
        self.kg = kg
        self.vl = vl
        self.fulfilled_count = 0

    def execute_batch(self, max_requests: int = 3) -> dict:
        """
        从队列取最紧急的请求, 执行搜索 + 同化。

        返回: {fulfilled, new_relations, errors}
        """
        if not self.queue:
            return {"fulfilled": 0, "new_relations": 0}

        # 取最紧急的
        pending = sorted(self.queue, key=lambda r: -r.urgency)[:max_requests]
        total_new = 0

        for req in pending:
            try:
                self.queue.remove(req)
                if not self.web_search or not self.kg:
                    continue

                results = self.web_search.search(req.query, max_results=3)
                new_for_this = 0

                for r in results:
                    if not r.snippet or "未连接" in r.snippet:
                        continue

                    # IA+KA 管道
                    pipe = __import__('AsteriaMind.text_pipeline',
                                      fromlist=['TextPipelineFull'])
                    tp = pipe.TextPipelineFull(self.kg)
                    result = tp.process(r.snippet, source_name=r.title[:30],
                                       credibility=r.source_credibility)
                    new_for_this += len(result.get("claims", []))

                total_new += new_for_this
                if new_for_this:
                    # 增量更新向量
                    if self.vl:
                        new_keys = [rl.key() for rl in self.kg.relations
                                    if rl.key() not in {vr.relation_key for vr in self.vl.relations}]
                        if new_keys:
                            new_rels = [rl for rl in self.kg.relations if rl.key() in new_keys]
                            self.vl.batch_index(new_rels)

            except Exception as e:
                pass  # 单条请求失败不影响其他

        self.fulfilled_count += 1
        return {"fulfilled": len(pending), "new_relations": total_new}
