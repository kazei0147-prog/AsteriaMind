"""
WorldModel — AsteriaMind 的内世界仿真 + 预测-验证闭环 (v3.0)

不是又一个模块。是把 Knowledge 从"死存储"变成"活信念"的缺少的一环。

核心循环:
  Knowledge → Predict (基于已知关系推测未来) 
            → Observe Reality (外部观测) 
            → Compare (预测 vs 现实) 
            → Update (强化/削弱信念)

每个预测:
  - 基于哪些知识 (引用 source relations)
  - 预测了什么 (predicted value + confidence)
  - 现实是什么 (observed outcome)
  - 差距多大 (error)
  - 信念怎么调整 (alpha/beta update)
"""
import time, math
from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class Prediction:
    """一次预测: "根据 X, 我预测 Y, 置信度 Z" """
    id: str                                  # 唯一 ID
    description: str                         # "基于高湿度预测明天下雨"
    predicted_value: str                     # "rain=True"
    confidence: float                        # 基于 source 关系的联合置信度
    source_relations: List[str] = field(default_factory=list)  # 引用的知识 key
    timestamp: float = 0.0
    outcome: Optional[str] = None            # 事后填写
    was_correct: Optional[bool] = None       # 事后判断
    outcome_timestamp: float = 0.0

    def __post_init__(self):
        if self.timestamp == 0.0:
            self.timestamp = time.time()

    def verify(self, reality: str) -> bool:
        self.outcome = reality
        self.outcome_timestamp = time.time()
        self.was_correct = (self.predicted_value == reality)
        return self.was_correct


class WorldModel:
    """
    内世界仿真器。

    不是外部环境——是 AsteriaMind 在脑内"预演"未来的能力。
    基于 KnowledgeGraph 中的关系, 生成可验证的预测,
    然后用现实校验, 反向更新信念。
    """

    def __init__(self):
        self.prediction_history: List[Prediction] = []
        self._prediction_counter = 0

    # ── 预测 ──

    def predict(
        self,
        description: str,
        predicted_value: str,
        confidence: float,
        source_relations: List[str] = None,
    ) -> Prediction:
        """基于知识做出一次预测"""
        self._prediction_counter += 1
        p = Prediction(
            id=f"pred_{self._prediction_counter}",
            description=description,
            predicted_value=predicted_value,
            confidence=min(1.0, max(0.1, confidence)),
            source_relations=source_relations or [],
        )
        self.prediction_history.append(p)
        return p

    def predict_from_knowledge(self, kg, context: dict = None) -> List[Prediction]:
        """从 KnowledgeGraph 自动生成可验证的预测。

        扫描所有 IS_A、HAS_PROPERTY、PREDICTS 关系,
        每条关系产生一个可验证预测。
        """
        predictions = []
        for r in kg.relations:
            if r.belief.confidence < 0.3:
                continue  # 太不确定, 不预测

            if r.predicate in ("IS_A", "HAS_PROPERTY", "HAS_FORM"):
                p = self.predict(
                    description=f"基于'{r.key()}'预测",
                    predicted_value=r.object,
                    confidence=r.belief.confidence,
                    source_relations=[r.key()],
                )
                predictions.append(p)

            # 对于 PREDICTS 关系, 直接作为预测
            if r.predicate == "PREDICTS":
                p = self.predict(
                    description=f"基于'{r.subject}'的规律: {r.object}",
                    predicted_value=r.object,
                    confidence=r.belief.confidence,
                    source_relations=[r.key()],
                )
                predictions.append(p)

        return predictions

    # ── 验证 ──

    def verify_and_update(
        self,
        prediction_id: str,
        reality: str,
        kg=None,
    ) -> Optional[dict]:
        """
        用现实校验预测, 更新知识图谱中相关关系的信念。

        返回: {correct, delta_confidence, updated_relations}
        """
        pred = None
        for p in self.prediction_history:
            if p.id == prediction_id:
                pred = p
                break
        if pred is None:
            return None

        was_correct = pred.verify(reality)
        delta = 0.0

        # 更新引用的知识关系
        updated = []
        if kg and pred.source_relations:
            for key in pred.source_relations:
                parts = key.split("--[")
                if len(parts) < 2:
                    continue
                subject = parts[0].strip()
                rest = parts[1].split("]-->")
                if len(rest) < 2:
                    continue
                predicate = rest[0].strip()
                obj = rest[1].strip()

                weight = pred.confidence if was_correct else 0.5
                kg.observe(subject, predicate, obj, correct=was_correct,
                           weight=weight,
                           context=f"预测验证:{pred.description}" if not was_correct else "",
                           alternative=reality if not was_correct else "")

                rel = kg.query(subject, predicate)
                updated.append({
                    "key": key,
                    "updated_confidence": rel[0].confidence if rel else 0,
                    "trend": rel[0].growth_trend() if rel else "unknown",
                })
                if rel:
                    delta = rel[0].confidence - pred.confidence

        return {
            "prediction_id": prediction_id,
            "correct": was_correct,
            "predicted": pred.predicted_value,
            "reality": reality,
            "delta_confidence": round(delta, 3),
            "updated_relations": updated,
        }

    # ── 统计 ──

    def accuracy(self) -> dict:
        """预测准确率"""
        verified = [p for p in self.prediction_history if p.was_correct is not None]
        if not verified:
            return {"n_verified": 0, "accuracy": 0}
        correct = sum(1 for p in verified if p.was_correct)
        return {
            "n_verified": len(verified),
            "n_correct": correct,
            "accuracy": round(correct / len(verified), 3),
            "recent_5": [
                {"desc": p.description[:40], "correct": p.was_correct}
                for p in verified[-5:]
            ],
        }

    def pending(self) -> List[Prediction]:
        return [p for p in self.prediction_history if p.was_correct is None]
