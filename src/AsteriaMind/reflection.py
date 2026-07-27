"""
ReflectionEngine — 反映射闭环 (AsteriaMind v3.3)

不是"事后总结"——是 AM 的元认知学习循环:

  每次回答后:
    记录 (问题, 回答, 置信度, 涉及模块)
    ↓
  用户下一轮输入:
    检测反馈信号 (纠正/追问/转移/肯定)
    ↓
  会话结束时:
    生成自我评估 → 写入 MetaCognition (调整权重)
                    → 写入 MetaReasoning (真实预测误差)
                    → 下次会话中作为"上次我错在哪"的参考

核心指标:
  - 模块准确率追踪 (哪个模块的预测最常被纠正?)
  - 过度自信诊断 (高置信但被纠正 = 需要校准)
  - 失败模式识别 (哪些领域/关系类型最常出错?)
"""
import time, re
from dataclasses import dataclass, field
from collections import defaultdict


# ── 反馈信号枚举 ──

class FeedbackSignal:
    """从用户下一轮输入中提取的反馈信号"""
    CORRECTION = "correction"        # "不对"/"错了" → 负面
    ENGAGEMENT = "engagement"        # 追问同一话题 → 弱正面
    DISENGAGEMENT = "disengagement"  # 换话题 → 中性(可能回答不够好)
    EXPLICIT_POSITIVE = "positive"   # "对"/"是的" → 强正面
    AMBIGUOUS = "ambiguous"          # 无法判断
    SESSION_END = "session_end"      # 会话结束(无新输入)


# ── 单次交换记录 ──

@dataclass
class ExchangeRecord:
    """一轮对话的完整记录"""
    round_id: int
    timestamp: float
    question: str
    answer: str
    confidence: float
    action: str
    modules: dict = field(default_factory=dict)   # {module_name: contribution}
    planned_actions: list = field(default_factory=list)

    # 事后填充 (从下一轮输入推断)
    feedback_signal: str = ""
    feedback_detail: str = ""
    was_correct: bool = False         # 被用户确认还是纠正?


# ── 会话级反射器 ──

class SessionReflector:
    """
    跟踪一个会话的所有问答，管理反馈-评估-学习循环。
    """

    def __init__(self, session_id: str = ""):
        self.session_id = session_id or f"sess_{int(time.time())}"
        self.created_at = time.time()
        self.last_active = time.time()
        self.exchanges: list[ExchangeRecord] = []
        self.pending_exchange: ExchangeRecord = None  # 等待用户反馈
        self.round_counter = 0

        # 累积统计
        self.module_correct: dict[str, int] = defaultdict(int)
        self.module_total: dict[str, int] = defaultdict(int)

    # ── 记录 ──

    def record_exchange(self, question: str, answer: str,
                        confidence: float, action: str,
                        modules: dict = None,
                        planned_actions: list = None) -> ExchangeRecord:
        """记录本轮问答——等待下一轮用户输入来确定反馈"""
        self.round_counter += 1
        rec = ExchangeRecord(
            round_id=self.round_counter,
            timestamp=time.time(),
            question=question,
            answer=answer,
            confidence=confidence,
            action=action,
            modules=modules or {},
            planned_actions=planned_actions or [],
        )
        self.pending_exchange = rec
        self.exchanges.append(rec)
        self.last_active = time.time()
        return rec

    # ── 反馈捕获 —— ★ 闭环核心 ★ ──

    def capture_feedback(self, next_user_text: str) -> dict:
        """
        从用户下一轮输入中提取对上一轮回答的反馈信号。

        这是闭环的核心: AM 不是瞎猜"我答得好不好"，
        而是从用户的自然语言中提取真实反馈。
        """
        if not self.pending_exchange:
            return {"signal": FeedbackSignal.AMBIGUOUS,
                    "detail": "无待反馈记录", "was_correct": False}

        rec = self.pending_exchange
        text = next_user_text.strip().lower()
        was_correct = False

        # ── 1. 明确纠正 ──
        correction_patterns = [
            r'^(不对|不是|错了|错|不正确|没这回事|胡说)',
            r'^(wrong|incorrect|no[,!.\s])',
            r'应该?是',  # "应该是鸟类"
            r'其实(是|不是)',
            r'你搞错了',
        ]
        for pat in correction_patterns:
            if re.search(pat, text):
                rec.feedback_signal = FeedbackSignal.CORRECTION
                rec.feedback_detail = f"用户纠正: {next_user_text[:60]}"
                rec.was_correct = False
                was_correct = False
                break
        else:
            # ── 2. 明确肯定 ──
            positive_patterns = [
                r'^(对|是的|没错|正确|嗯嗯|好的?|明白了)',
                r'^(yes|correct|right|ok|got it|thanks)',
                r'那(.*?)呢',   # "那麻雀呢" → 接受答案+追问
            ]
            for pat in positive_patterns:
                if re.search(pat, text):
                    rec.feedback_signal = FeedbackSignal.EXPLICIT_POSITIVE
                    rec.feedback_detail = f"用户肯定: {next_user_text[:60]}"
                    rec.was_correct = True
                    was_correct = True
                    break
            else:
                # ── 3. 追问/延续同一话题 ──
                # 检查是否与上一轮问题共享关键词
                prev_keywords = self._extract_keywords(rec.question)
                curr_keywords = self._extract_keywords(next_user_text)
                shared = prev_keywords & curr_keywords
                if shared and len(text) > 3:
                    rec.feedback_signal = FeedbackSignal.ENGAGEMENT
                    rec.feedback_detail = f"用户追问(共享词: {shared}): {next_user_text[:60]}"
                    rec.was_correct = True  # 追问 = 答案至少部分正确
                    was_correct = True
                else:
                    # ── 4. 话题转移 ──
                    rec.feedback_signal = FeedbackSignal.DISENGAGEMENT
                    rec.feedback_detail = f"用户转移话题: {next_user_text[:60]}"
                    rec.was_correct = False  # 转移 = 答案可能不够好
                    was_correct = False

        # 更新模块统计
        for mod_name in rec.modules:
            self.module_total[mod_name] += 1
            if was_correct:
                self.module_correct[mod_name] += 1

        self.pending_exchange = None
        return {
            "signal": rec.feedback_signal,
            "detail": rec.feedback_detail,
            "was_correct": was_correct,
            "round_id": rec.round_id,
        }

    def close_session(self) -> dict:
        """会话自然结束(超时/用户离开)——对最后一轮做中性标记"""
        if self.pending_exchange:
            rec = self.pending_exchange
            rec.feedback_signal = FeedbackSignal.SESSION_END
            rec.feedback_detail = "会话结束——无法获取直接反馈"
            rec.was_correct = False  # 保守: 未确认 = 未证明正确
            for mod_name in rec.modules:
                self.module_total[mod_name] += 1
            self.pending_exchange = None
        return {"signal": FeedbackSignal.SESSION_END,
                "detail": "会话结束", "was_correct": False}

    # ── 自我评估 —— ★ 闭环输出 ★ ──

    def _extract_keywords(self, text: str) -> set:
        """提取中文关键词"""
        words = set(re.findall(r'[\u4e00-\u9fff]{2,}', text))
        return words

    def generate_self_assessment(self) -> dict:
        """
        会话结束时的自我评估。

        不是模板——是基于真实数据的结构化诊断:
          1. 整体准确率
          2. 模块级准确率 (谁该降权?)
          3. 过度自信诊断 (高置信+低正确 = 需要校准)
          4. 失败模式 (哪些领域/动作类型最常出错?)
          5. 改进建议
        """
        if not self.exchanges:
            return {"status": "empty_session", "summary": "本次会话无问答记录"}

        # ── 1. 整体统计 ──
        total = len(self.exchanges)
        confirmed = sum(1 for e in self.exchanges if e.was_correct)
        corrected = sum(1 for e in self.exchanges
                       if e.feedback_signal == FeedbackSignal.CORRECTION)
        accuracy = confirmed / total if total > 0 else 0.0

        # ── 2. 模块级准确率 ──
        module_accuracy = {}
        for mod_name in self.module_total:
            total_m = self.module_total[mod_name]
            correct_m = self.module_correct.get(mod_name, 0)
            module_accuracy[mod_name] = {
                "correct": correct_m,
                "total": total_m,
                "accuracy": correct_m / total_m if total_m > 0 else 0.0,
            }

        # ── 3. 过度自信诊断 ──
        overconfident = []
        for e in self.exchanges:
            if e.confidence > 0.7 and not e.was_correct and e.feedback_signal:
                overconfident.append({
                    "round": e.round_id,
                    "question": e.question[:50],
                    "confidence": e.confidence,
                    "feedback": e.feedback_signal,
                    "detail": e.feedback_detail,
                })

        # ── 4. 失败模式 ──
        action_errors = defaultdict(lambda: {"correct": 0, "total": 0})
        for e in self.exchanges:
            action_errors[e.action]["total"] += 1
            if e.was_correct:
                action_errors[e.action]["correct"] += 1

        failing_actions = []
        for action, stats in action_errors.items():
            if stats["total"] >= 2:
                acc = stats["correct"] / stats["total"]
                if acc < 0.5:
                    failing_actions.append({
                        "action": action,
                        "accuracy": acc,
                        "total": stats["total"],
                        "correct": stats["correct"],
                    })

        # ── 5. 生成改进建议 ──
        suggestions = []

        if accuracy < 0.5 and total >= 3:
            suggestions.append({
                "priority": "high",
                "type": "calibration",
                "message": f"整体准确率仅 {accuracy:.0%}——建议全面降低置信度阈值",
            })

        if overconfident:
            suggestions.append({
                "priority": "high" if len(overconfident) >= 3 else "medium",
                "type": "overconfidence",
                "message": f"发现 {len(overconfident)} 次过度自信 (高置信但被纠正)——需要校准置信度",
                "details": overconfident,
            })

        for mod, stats in module_accuracy.items():
            if stats["total"] >= 2 and stats["accuracy"] < 0.4:
                suggestions.append({
                    "priority": "medium",
                    "type": "module_weight",
                    "module": mod,
                    "message": f"模块 '{mod}' 准确率仅 {stats['accuracy']:.0%} ({stats['correct']}/{stats['total']})——建议降低投票权重",
                })

        if failing_actions:
            action_names = [a["action"] for a in failing_actions]
            suggestions.append({
                "priority": "medium",
                "type": "action_pattern",
                "message": f"行动类型 {action_names} 准确率低——该领域可能缺乏足够知识",
                "failing_actions": failing_actions,
            })

        return {
            "session_id": self.session_id,
            "timestamp": time.time(),
            "duration_seconds": time.time() - self.created_at,
            "total_exchanges": total,
            "confirmed": confirmed,
            "corrected": corrected,
            "accuracy": accuracy,
            "module_accuracy": module_accuracy,
            "overconfidence_count": len(overconfident),
            "overconfident_cases": overconfident[:5],
            "failing_actions": failing_actions,
            "suggestions": suggestions,
            "status": "healthy" if accuracy >= 0.6 else "needs_improvement",
            "summary": (
                f"本次会话共 {total} 轮, 准确率 {accuracy:.0%}。"
                f"{confirmed} 次确认, {corrected} 次纠正。"
                f"{'需注意: ' + suggestions[0]['message'] if suggestions else '表现良好。'}"
            ),
        }

    def get_lessons_for_next_session(self) -> dict:
        """
        提取"下次会话应该注意什么"的结构化教训。
        喂给 meta_cognition 作为先验权重调整。
        """
        assessment = self.generate_self_assessment()
        return {
            "session_id": self.session_id,
            "accuracy": assessment["accuracy"],
            "module_weights": {
                mod: stats["accuracy"]
                for mod, stats in assessment.get("module_accuracy", {}).items()
                if stats["total"] >= 2
            },
            "failing_actions": assessment.get("failing_actions", []),
            "overconfidence_warning": assessment["overconfidence_count"] > 0,
            "suggestions": assessment.get("suggestions", []),
        }
