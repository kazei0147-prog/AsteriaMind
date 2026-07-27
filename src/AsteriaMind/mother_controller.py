"""
MotherController — 认知调度主循环 (AsteriaMind v3.3)

不是旧的全权 MotherFallback。

只是每轮跑一次的轻量管道:
  Semantic → Pragmatic → ActiveInference → MetaCognition → 行动选择

v3.3: 反映射闭环 — loop() 接受上轮反馈, 在下一轮开始前喂给
       MetaReasoning (真实预测误差) + MetaCognition (模块权重调整),
       形成"回答→反馈→学习→下次更好"的闭环。
"""
from AsteriaMind.active_inference import ActiveInferenceEngine
from AsteriaMind.meta_cognition import MetaCognition
from AsteriaMind.meta_reasoning import MetaReasoningLayer


def _structure_to_language(cog: dict) -> str:
    """
    极简语言生成器——从结构化认知输出到自然语言。

    不是模板: 是从 language_traces 检索句式骨架 + 替换实体。
    v2: 支持主动推理建议织入回复。
    """
    action = cog.get("action", "unknown")
    subj = cog.get("subject", "")
    pred = cog.get("relation", "")
    obj = cog.get("object", "") or ""
    conf = cog.get("confidence", 0.5)
    evidence = cog.get("evidence", [])
    diffs = cog.get("differences", [])

    base = ""  # 基础回复, 末尾统一追加主动建议

    if action == "fact_learn":
        parts = [f"✅ 学到了: {subj}"]
        if pred:
            parts.append(pred)
        if obj:
            parts.append(obj)
        base = " ".join(parts)

    elif action == "info_request":
        source = cog.get("source", "")
        if not evidence:
            base = f"关于「{subj}」我还不了解。你能教我吗?"
        elif source == "online_learning":
            parts = [f"我刚查了一下——"]
            ev_short = evidence[:2]
            parts.append(f"「{ev_short[0]}」")
            if len(ev_short) > 1:
                parts.append(f"，还有「{ev_short[1]}」")
            parts.append(f"。(置信 {conf:.0%})")
            base = " ".join(parts)
        elif source == "knowledge_gap":
            base = f"关于「{subj}」和「{obj}」的关系，我查了但没找到可靠信息。你能教我吗?"
        elif conf > 0.5:
            head = "对" if conf > 0.7 else "应该对"
            parts = [f"{head}——"]
            ev_short = evidence[:2]
            parts.append(f"比如「{ev_short[0]}」")
            if len(ev_short) > 1:
                parts.append(f"和「{ev_short[1]}」都知道;")
            if diffs:
                parts.append(f"但{diffs[0]}不同。")
            parts.append(f"(置信 {conf:.0%})")
            base = " ".join(parts)
        elif conf > 0.3:
            base = f"不太确定——关于「{subj}」和「{obj}」的关系。你能确认吗?"
        else:
            base = f"关于「{subj}」我还不知道。你能教我吗?"

    elif action == "self_directed":
        base = f"我是 AsteriaMind。{evidence[0] if evidence else ''}"

    elif action == "uncertain" or action == "observe":
        base = f"我不太确定你的意思。试试说「X是Y」或「X会Y吗」?"

    else:
        base = f"[{action}] {subj} {pred} {obj}"

    # ── 主动推理: 高分探索/验证计划 → 织入回复末尾 ──
    planned = cog.get("planned_actions", [])
    if planned and planned[0].get("score", 0) > 0.15 and base:
        top = planned[0]
        atype = top.get("action_type", "")
        if atype in ("explore", "verify"):
            base += (
                f"\n💡 顺便一提——我注意到「{top['subj']} {top['pred']} {top['obj']}」"
                f"还不太确定。需要我查一下吗?"
            )
        elif atype == "clarify":
            base += (
                f"\n🤔 另外, 关于「{top['subj']} {top['pred']} {top['obj']}」"
                f"我有些矛盾信息——你能帮我确认吗?"
            )
        elif atype == "suggest":
            base += (
                f"\n📌 我还知道: {top['subj']} {top['pred']} {top['obj']}。"
            )

    return base


class MotherController:
    """
    主循环——不控制模块内部, 只决定每轮执行顺序。
    """

    def __init__(self, star_map=None, kg=None, db=None, active_learner=None,
                 reflector=None):
        self.star_map = star_map
        self.kg = kg
        self.db = db
        self.active_learner = active_learner  # 在线学习: 知识空白时对外查询
        self.reflector = reflector  # v3.3: SessionReflector 反馈采集
        self.active_inference = ActiveInferenceEngine(star_map)
        self.meta_cognition = MetaCognition()
        self.meta_reasoning = MetaReasoningLayer()
        self.round_count = 0

    def loop(self, semantic_result: dict, pragmatic_result: dict,
             text: str, reflection_ctx: dict = None) -> dict:
        """
        一轮认知调度 (v3.3: 含反馈闭环)。

        输入: Semantic + Pragmatic 的结构化结果
              + 可选的 reflection_ctx (含上轮反馈信号)
        输出: { reply, action, confidence, reflection_ctx, ... }
        """
        self.round_count += 1

        # ── 0. 反馈闭环: 处理上轮反馈 ★ v3.3 ★ ──
        prev_feedback = None
        if reflection_ctx and reflection_ctx.get("pending_feedback"):
            prev_feedback = reflection_ctx["pending_feedback"]
            was_correct = prev_feedback.get("was_correct", False)
            prev_conf = reflection_ctx.get("last_confidence", 0.5)
            prev_modules = reflection_ctx.get("last_modules", {})

            # → MetaReasoning: 真实预测误差
            self.meta_reasoning.record_outcome("direct", was_correct, prev_conf)

            # → MetaCognition: 调整各模块投票权重
            for mod_name in prev_modules:
                self.meta_cognition.learn_from_reflection(mod_name, was_correct)
        else:
            was_correct = None
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

        # ── 3. 产生结构化认知输出 (不是文本) ──
        cognitive_output = {
            "subject": subj,
            "relation": pred,
            "object": obj,
            "confidence": confidence,
            "action": action,
            "evidence": [],
            "differences": [],
        }

        if action == "fact_learn":
            if subj and pred and obj and self.star_map:
                self.star_map.store(subj, pred, obj, "confirmed", text)
                self.active_inference.update_from_feedback(subj, pred, obj, True)
                cognitive_output["evidence"] = [f"{subj} {pred} {obj} (新学习)"]

        elif action == "info_request" and subj and pred and obj and self.star_map:
            er = self.star_map.emergent_reply(text, subj, pred, obj)
            cognitive_output["confidence"] = er.get("confidence", confidence)
            cognitive_output["evidence"] = [
                f"{e['subj']} {e.get('pred',pred)} {e['obj']}" 
                for e in er.get("evidence", [])[:3]
            ]
            # 差异: 共享谓词但对象不同的痕迹
            if cognitive_output["evidence"]:
                cognitive_output["differences"] = [
                    e['obj'] for e in er.get("evidence", [])[:3]
                    if e.get('obj') != obj
                ]

            # ── 在线学习: 无直接匹配证据 → 触发 ActiveLearner 对外查询 ──
            er_conf = er.get("confidence", 0)
            er_ev = er.get("evidence", [])
            # 检查是否有直接匹配 (subj 和 obj 都匹配)
            has_direct = any(
                e.get("subj") == subj and e.get("obj") == obj
                for e in er_ev
            ) if er_ev else False
            if not has_direct and self.active_learner:
                learn_result = self.active_learner.learn_relation(subj, pred, obj)
                if learn_result.get("learned"):
                    # 搜到了 → 更新证据 + belief
                    cognitive_output["evidence"] = [
                        f"{f['subj']} {f['pred']} {f['obj']} (网络学习)"
                        for f in learn_result.get("facts", [])[:3]
                    ]
                    cognitive_output["confidence"] = 0.6
                    cognitive_output["source"] = "online_learning"
                    # 重新查星图获取更新后的预测
                    er2 = self.star_map.emergent_reply(text, subj, pred, obj)
                    if er2.get("evidence"):
                        cognitive_output["evidence"].extend(
                            f"{e['subj']} {e.get('pred',pred)} {e['obj']}"
                            for e in er2["evidence"][:2]
                        )
                    # 贝叶斯更新
                    self.active_inference.update_from_feedback(subj, pred, obj, True)
                elif learn_result.get("known"):
                    # 星图已有足够证据 — 不需要对外查询
                    pass
                else:
                    # 搜不到 → 标记知识缺口
                    cognitive_output["source"] = "knowledge_gap"

        elif action == "self_directed":
            cognitive_output["evidence"] = [f"星图痕迹: {self.star_map.count() if self.star_map else 0}"]

        # ── 3.5. ActiveInference: 预测下一步该主动做什么 ──
        # 这是"在线推理链"的核心: 不是被动检索→回复,
        # 而是主动评估"哪些知识缺口最值得现在填补"
        planned = self._plan_proactive_actions(subj, pred, obj, top_k=2)
        cognitive_output["planned_actions"] = planned

        # ── 4. 语言生成: 从结构到文本 ──
        reply = _structure_to_language(cognitive_output)

        # ── 5. 记录本轮交换 + 构建下轮反馈上下文 ★ v3.3 ★ ──
        new_reflection_ctx = {}
        if self.reflector:
            # 记录本轮问答 (反馈由下一轮用户输入确定)
            self.reflector.record_exchange(
                question=text,
                answer=reply,
                confidence=confidence,
                action=action,
                modules={
                    "semantic": 1.0,
                    "pragmatic": 1.0,
                    "meta_cognition": 1.0,
                },
                planned_actions=cognitive_output.get("planned_actions", []),
            )
            # 返回上下文供下轮反馈处理
            new_reflection_ctx = {
                "session_id": self.reflector.session_id,
                "last_round": self.round_count,
                "last_confidence": confidence,
                "last_modules": {
                    "semantic": 1.0,
                    "pragmatic": 1.0,
                    "meta_cognition": 1.0,
                },
            }

        # ── 6. MetaReasoning: 定期反思 (每20轮或首次) ──
        if self.round_count % 20 == 1 or self.round_count == 1:
            reflections = self.meta_reasoning.reflect()
            if reflections:
                cognitive_output["meta_reflections"] = [
                    r["observation"] for r in reflections[:3]
                ]

        return {
            "reply": reply,
            "action": action,
            "confidence": confidence,
            "belief": belief,
            "arbitration": arbitration,
            "cognitive": cognitive_output,
            "reflection_ctx": new_reflection_ctx,     # ★ v3.3
            "prev_feedback": prev_feedback,            # ★ v3.3: 上轮反馈结果
            "was_correct_last": was_correct,           # ★ v3.3: 上轮是否正确
        }

    def get_health(self) -> dict:
        """系统健康报告——暴露给 /api/health"""
        return self.meta_reasoning.get_system_health()

    def _plan_proactive_actions(self, subj: str, pred: str, obj: str,
                                 top_k: int = 2) -> list[dict]:
        """
        Active Inference 在线规划 —— "基于当前对话，下一步该主动做什么？"

        从星图中提取与当前上下文相关的候选边，
        用 BudgetContest 评分 → 映射为可执行行动类型。
        """
        if not subj or not self.star_map:
            return []

        star = self.star_map
        candidates = []
        seen = set()

        # ── 1. 当前查询的精确边 ──
        if pred and obj:
            key = (subj, pred, obj)
            if key not in seen:
                candidates.append(key)
                seen.add(key)

        # ── 2. 同主语的其他边 ──
        try:
            for row in star.conn.execute(
                "SELECT subj, pred, obj FROM cognitive_traces WHERE subj=? LIMIT 20",
                (subj,)
            ):
                key = (row[0], row[1], row[2])
                if key not in seen:
                    candidates.append(key)
                    seen.add(key)
        except Exception:
            pass

        # ── 3. 同宾语的反向查询 ──
        if obj:
            try:
                for row in star.conn.execute(
                    "SELECT subj, pred, obj FROM cognitive_traces WHERE obj=? LIMIT 10",
                    (obj,)
                ):
                    key = (row[0], row[1], row[2])
                    if key not in seen:
                        candidates.append(key)
                        seen.add(key)
            except Exception:
                pass

        # ── 4. 共享谓词的其他边 —— "同类关系" ──
        if pred:
            try:
                for row in star.conn.execute(
                    "SELECT subj, pred, obj FROM cognitive_traces "
                    "WHERE pred=? AND subj!=? LIMIT 8",
                    (pred, subj)
                ):
                    key = (row[0], row[1], row[2])
                    if key not in seen:
                        candidates.append(key)
                        seen.add(key)
            except Exception:
                pass

        if not candidates:
            return []

        return self.active_inference.plan_actions(candidates, top_k=top_k)
