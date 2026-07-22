"""
TextPipeline — IA+KA 完整管道 (v3.1)

不是正则匹配——是文本→主张→溯源→同化 四阶段管道。

阶段1: 文本清洗 → 分词 → 候选主张提取
阶段2: 主张 → 溯源 (记录出处、时间、可信度、衰减)
阶段3: 主张 → 知识图同化 (冲突/接受/拒绝/竞技场)
阶段4: 同化 → 反射 (元假说监控: 我是不是所有东西都信了? 还是全不信?)
"""
import time
from dataclasses import dataclass, field
from typing import List, Optional
from AsteriaMind.datasource import TextIngestor, KnowledgeAssimilator, DataPipeline


@dataclass
class SourceRecord:
    """每个信息来源的档案"""
    name: str
    credibility: float             # 初始可信度 [0,1]
    first_seen: float = 0.0
    claims_made: int = 0
    claims_accepted: int = 0
    claims_rejected: int = 0
    claims_conflicted: int = 0

    def __post_init__(self):
        if self.first_seen == 0.0:
            self.first_seen = time.time()

    @property
    def acceptance_rate(self) -> float:
        total = self.claims_accepted + self.claims_rejected + self.claims_conflicted
        return self.claims_accepted / max(1, total)

    @property
    def adjusted_credibility(self) -> float:
        """来源可信度随时间衰减, 但如果接受率持续高, 衰减更慢"""
        age = time.time() - self.first_seen
        decay = 0.99 ** (age / 86400)  # 每天衰减 1%
        rate_bonus = 0.5 + 0.5 * self.acceptance_rate
        return self.credibility * decay * rate_bonus


class TextPipelineFull:
    """
    完整文本→知识管道。

    用法:
      pipeline = TextPipelineFull(kg, data_pipeline)
      pipeline.process("咖啡降低疾病风险但增加焦虑", source="哈佛研究", credibility=0.8)
    """

    def __init__(self, kg, data_pipeline: DataPipeline = None):
        self.kg = kg
        self.data_pipeline = data_pipeline
        self.ingestor = TextIngestor()
        self.assimilator = KnowledgeAssimilator(kg, data_pipeline)
        self.sources: dict[str, SourceRecord] = {}
        self.total_texts_processed = 0
        self.total_claims_extracted = 0

    def process(self, text: str, source_name: str = "unknown",
                credibility: float = 0.5) -> dict:
        """
        完整处理一段文本。
        返回 {claims, results, source_status, reflection}
        """
        self.total_texts_processed += 1

        # ── 阶段1: 溯源 ──
        if source_name not in self.sources:
            self.sources[source_name] = SourceRecord(
                name=source_name, credibility=credibility)
        source = self.sources[source_name]

        # ── 阶段2: 提取主张 ──
        claims = self.ingestor.ingest(text, source_name=source_name,
                                      source_credibility=source.adjusted_credibility)
        self.total_claims_extracted += len(claims)
        source.claims_made += len(claims)

        # ── 阶段3: 同化 ──
        results = self.assimilator.assimilate(claims)
        source.claims_accepted += results["accepted"]
        source.claims_rejected += results["rejected"]
        source.claims_conflicted += results["conflicted"]

        # ── 阶段4: 反射 ──
        reflection = self._reflect(source, results, claims)

        return {
            "claims": claims,
            "results": results,
            "source_status": {
                "name": source_name,
                "credibility": round(source.adjusted_credibility, 3),
                "acceptance_rate": round(source.acceptance_rate, 3),
                "total_claims": source.claims_made,
            },
            "reflection": reflection,
        }

    def _reflect(self, source: SourceRecord, results: dict, claims: list) -> str:
        """
        管道反射: 我是太信了还是太不信了?

        这个反射不修改任何东西——它只是产生一个可读的自我诊断。
        元假说层可能会基于这个反射来调整管道本身。
        """
        acc_rate = source.acceptance_rate
        rej_rate = results["rejected"] / max(1, sum(results.values()))
        confl_rate = results["conflicted"] / max(1, sum(results.values()))

        if confl_rate > 0.5:
            return (f"高度冲突: {confl_rate*100:.0f}% 的主张与已有信念冲突。"
                    f"可能是来源\"{source.name}\"的观点与现有知识体系不兼容,"
                    f"或者知识图的核心假设需要重新审视。")
        elif rej_rate > 0.5:
            return (f"高拒绝率: {rej_rate*100:.0f}% 的主张被视为不可靠。"
                    f"来源\"{source.name}\"的可信度({source.adjusted_credibility:.2f})可能过高估计。")
        elif acc_rate > 0.8 and source.claims_made > 5:
            return (f"来源\"{source.name}\"高度可靠: 接受率 {acc_rate*100:.0f}%。"
                    f"该来源的主张持续与已有知识一致, 可以逐步提高默认信任。")
        else:
            return f"来源\"{source.name}\"的主张正在被常规同化。无异常模式。"

    def source_report(self) -> str:
        """所有来源的可信度报告"""
        lines = [f"  {'来源':20s} {'可信度':>6s} {'接受率':>6s} {'主张':>4s} {'状态':>8s}"]
        for name, src in sorted(self.sources.items(),
                                key=lambda x: -x[1].adjusted_credibility):
            status = "可靠" if src.acceptance_rate > 0.7 else "争议" if src.claims_conflicted > 0 else "待评估"
            lines.append(f"  {name:20s} {src.adjusted_credibility:5.3f}  "
                        f"{src.acceptance_rate:5.3f}  {src.claims_made:>3d}  {status:>8s}")
        return "\n".join(lines)
