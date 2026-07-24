"""
MotherController — 认知调度主循环 (AsteriaMind v3)

不是旧的全权 MotherFallback。

只是每轮跑一次的轻量管道:
  Semantic → Pragmatic → ActiveInference → MetaCognition → 行动选择
"""
from AsteriaMind.active_inference import ActiveInferenceEngine
from AsteriaMind.meta_cognition import MetaCognition
from AsteriaMind.meta_reasoning import MetaReasoningLayer


class MotherController:
    """
    主循环——不控制模块内部, 只决定每轮执行顺序。
    """

    def __init__(self, star_map=None, kg=None, db=None):
        self.star_map = star_map
        self.kg = kg
        self.db = db
        self.active_inference = ActiveInferenceEngine(star_map)
        self.meta_cognition = MetaCognition()
        self.meta_reasoning = MetaReasoningLayer()
        self.round_count = 0

    def loop(self, semantic_result: dict, pragmatic_result: dict,
             text: str) -> dict:
        """
        一轮认知调度。

        输入: Semantic + Pragmatic 的结构化结果
        输出: { reply, action, confidence, ... }
        """
        self.round_count += 1
        sem = semantic_result
        prag = pragmatic_result
        struct = sem.get("structure", {}) if isinstance(sem, dict) else getattr(sem, "structure", {})
        subj = struct.get("subject", "")
        pred = struct.get("predicate", "")
        obj = struct.get("object", "") or ""
        prag_type = prag.get("type", "unknown") if isinstance(prag, dict) else getattr(prag, "type", "unknown")

        # ── 1. ActiveInference: 查询信念 ���─
        belief = None
        if subj and pred:
            belief = self.active_inference.perceive(subj, pred, obj)

        # ── 2. MetaCognition: 多信号加权仲裁 ──
        # 语义信号 → 映射为行动类型
        is_question = struct.get("question", False)
        has_full_triple = bool(subj and pred and obj and pred not in ("IS_TOPIC", "UNPARSED"))
        sem_action = "info_request" if is_question else ("fact_learn" if has_full_triple else "observe")
        sem_conf = sem.get("confidence", 0.5) if isinstance(sem, dict) else 0.5

        signals = {
            "semantic": {"action": sem_action, "confidence": sem_conf},
            "pragmatic": {"action": prag_type, "confidence": prag.get("confidence", 0.5) if isinstance(prag, dict) else 0.5},
        }
        if belief:
            signals["belief"] = {
                "action": "confirmed" if belief["belief"] > 0.5 else "corrected",
                "confidence": belief["belief"],
            }
        arbitration = self.meta_cognition.arbitrate(signals)
        action = arbitration["action"]
        confidence = arbitration["confidence"]

        # ── 3. 根据仲裁结果选择行动 ──
        reply = ""
        store_feedback = None

        if action == "fact_learn":
            # 学习路径: 存星图 + 更新信念
            if subj and pred and obj and self.star_map:
                self.star_map.store(subj, pred, obj, "confirmed", text)
                self.active_inference.update_from_feedback(subj, pred, obj, True)
            reply = f"✅ 学会了: {subj} {pred} {obj}"
            store_feedback = ("confirmed", True)

        elif action == "info_request":
            if belief and belief["belief"] > 0.5:
                reply = f"对——这个说法我比较确定 (信念 {belief['belief']:.0%})"
            elif belief and belief["belief"] < 0.5:
                reply = f"不对——这个说法我比较怀疑 (信念 {belief['belief']:.0%})"
            elif subj and pred and obj and self.star_map:
                # 星图查询: 找最近的认知痕迹
                er = self.star_map.emergent_reply(text, subj, pred, obj)
                reply = er.get("reply", f"关于 {subj} 我还不知道。")
            else:
                reply = f"我还不确定——你能教我吗?"

        elif action == "self_directed":
            facts = self.star_map.count() if self.star_map else 0
            reply = f"我是 AsteriaMind, 星图有 {facts} 条认知痕迹。"

        elif action == "uncertain":
            reply = f"我不太确定你的意思 😅"

        else:
            reply = f"我听到了。(action={action})"

        # ── 4. MetaReasoning: 记录预测误差 ──
        if belief and belief.get("belief") is not None:
            predicted = belief["belief"]
            # 实际反馈: 如果用户继续这条对话且没有纠正 → 视为 confirmed
            # 这里用 0.5 作为默认先验
            self.meta_reasoning.record_prediction(
                strategy="direct",
                predicted=predicted,
                actual=0.5,  # 未知, 等待下一轮确认
                importance=1.0,
            )

        return {
            "reply": reply,
            "action": action,
            "confidence": confidence,
            "belief": belief,
            "arbitration": arbitration,
        }

    def get_health(self) -> dict:
        """系统健康报告——暴露给 /api/health"""
        return self.meta_reasoning.get_system_health()
