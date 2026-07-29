"""
LanguageGenerator — 统计语料库驱动的表达生成器 (AsteriaMind v3.4)

不是模板引擎。
是 AM 的语言涌现层: 从 language_traces 语料库中学习词序、搭配和表达方式。

三级进化:
  1. 冷启动: 回退到模板 (与当前 _structure_to_language 等价)
  2. 积累期: 语料库开始统计词级共现和场景-表达映射
  3. 质变期: 语料库足够丰富 → 完全由统计驱动, 表达多样性自然涌现

实现原理:
  - 把每个生成的回复拆解为 opener + body + closer
  - 所有组件写入 word_cooccur 表 (词级搭配) 和 lang_patterns 表 (场景-表达映射)
  - 下次生成时, 查询统计 → 加权选择最自然的表达
  - 冷启动时语料稀疏 → 自动回退模板
"""
import time, re, random


class LanguageGenerator:
    """语料库驱动的自然语言生成器"""

    def __init__(self, star_map=None):
        self.star_map = star_map  # CognitiveStarMap 实例

    # ── 公开接口 ──

    def generate(self, cognitive_output: dict) -> str:
        """
        从结构化认知输出生成自然语言。

        优先级:
          1. language_traces 原始语料 (真实句子 → 学语气和词序)
          2. lang_patterns 统计抽象 (频率统计 → 学常见表达)
          3. 模板回退
        """
        action = cognitive_output.get("action", "unknown")
        subj = cognitive_output.get("subject", "")
        pred = cognitive_output.get("relation", "")
        obj = cognitive_output.get("object", "") or ""
        conf = cognitive_output.get("confidence", 0.5)
        evidence = cognitive_output.get("evidence", [])
        source = cognitive_output.get("source", "")
        diffs = cognitive_output.get("differences", [])

        bucket = self._confidence_bucket(conf)

        # ── v3.6: 能量驱动的策略选择 ──
        energy_level = "medium"
        if self.star_map and hasattr(self.star_map, 'energy_level'):
            energy_level = self.star_map.energy_level()
        if energy_level == "critical":
            return ("我的认知能量很低——很多节点的激活不足。"
                    "你可以教我新知识来帮我恢复能量。")

        # ── v3.5: 能量驱动的认知焦点 → 优先使用激活上下文 ──
        focus = cognitive_output.get("cognitive_focus", "regex")
        activation = cognitive_output.get("activation")

        if focus == "activation_driven" and activation:
            # ── v3.6: 关系驱动的叙事生成 ──
            narrative = self._compose_narrative(subj, activation, evidence)
            if narrative:
                return narrative
            # 回退: 单节点
            top = activation[0]
            top_node = top["node"]
            top_energy = top["energy"]
            if any(t.startswith("self_anchor") for t in top.get("triggers", [])):
                return ("我是 AsteriaMind——一个基于认知星图和能量扩散的学习系统。"
                        "你可以教我知识，向我提问，或者让我搜索。")
            if top_energy > 2.0:
                if evidence: return f"关于「{top_node}」——{evidence[0][:120]}"
                return f"我对「{top_node}」有些了解。你想知道哪方面？"
            return f"「{subj}」让我联想到了「{top_node}」——你是想了解这方面的知识吗？"

        # ── 原有逻辑链 ──
        if self.star_map:
            lt = self._query_language_traces(action, pred, bucket)
            if lt and len(lt.get("sentences", [])) >= 2:
                result = self._generate_from_traces(
                    lt, subj, pred, obj, evidence, diffs, conf)
                if result and "{subj}" not in result and "{obj}" not in result \
                        and len(result) >= 4:
                    return result
            patterns = self.star_map.query_expression_patterns(
                action, bucket, source, min_count=2, top_k=5)
            if patterns and len(patterns) >= 2:
                return self._generate_from_corpus(
                    patterns, subj, pred, obj, evidence, diffs, conf, action)
        return self._fallback_template(
            action, subj, pred, obj, conf, evidence, diffs, source)

    def _binding_confidence(self, subj: str, pred: str = "", obj: str = "") -> float:
        """
        v3.5: 基于信息熵的骨架绑定置信度。

        不是"hello 看起来像实体吗?"——是"hello 在星图中有语义权重吗?"
        节点度为 0 + 无共现 → 信息量太低 → 不应与知识骨架绑定。

        "hello"   → 节点度 0, 共现 0  → confidence 0.0 → 回退社交路径
        "嗯"      → 节点度 0, 共现 0  → confidence 0.0 → 回退
        "企鹅"    → 节点度 22, 共现 15 → confidence 0.92 → 正常绑定
        """
        if not subj or not self.star_map:
            return 0.0

        degree = 0
        try:
            # cognitive_traces 中的节点度
            for row in self.star_map.conn.execute(
                "SELECT COUNT(*) FROM cognitive_traces WHERE subj=? OR obj=?",
                (subj, subj)
            ):
                degree = row[0]
            # co_occurrence 中的共现边权 (折半计入)
            for row in self.star_map.conn.execute(
                "SELECT COUNT(*) FROM co_occurrence WHERE entity_a=? OR entity_b=?",
                (subj, subj)
            ):
                degree += row[0] * 0.5
        except Exception:
            pass

        if degree == 0:
            return 0.0

        # 对数缩放: 1-2 条边≈0.3, 5 条≈0.5, 20 条≈0.9
        import math
        return min(1.0, math.log(degree + 1) / math.log(10))

    def learn_from_reply(self, cognitive_output: dict, reply: str):
        """
        学习闭环: 把生成的回复拆解为组件, 喂入语料库。

        每次调用 generate() 后调用此方法,
        形成"生成 → 记录 → 下次更好的统计"的正反馈循环。
        """
        if not self.star_map or not reply:
            return

        action = cognitive_output.get("action", "unknown")
        conf = cognitive_output.get("confidence", 0.5)
        source = cognitive_output.get("source", "")
        bucket = self._confidence_bucket(conf)
        subj = cognitive_output.get("subject", "")
        pred = cognitive_output.get("relation", "")
        obj = cognitive_output.get("object", "") or ""

        # 拆解回复
        opener, body, closer = self._decompose_reply(reply)

        # → lang_patterns: 记录 (场景, 表达方式)
        self.star_map.learn_expression_pattern(
            action, bucket, source, opener, body, closer)

        # → word_cooccur: 记录词级搭配
        ctx = f"{action}-{bucket}"
        self._feed_word_cooccur(opener, body, closer, subj, pred, obj, ctx)

    # ── language_traces 原始语料查询 ──

    def _infer_pattern_types(self, action: str, pred: str) -> list[str]:
        """根据行动类型和谓词推断可能的语言模式"""
        patterns = []
        if action == "fact_learn":
            patterns = ["X是Y", "X会Y", "X属于Y", "陈述"]
        elif action == "info_request":
            # 回答时: 优先答句模式, 非问句
            patterns = ["陈述", "X是Y", "X会Y"]
            if pred == "IS_A":
                patterns = ["X是Y", "陈述", "X属于Y"]
            elif pred == "CAN":
                patterns = ["X会Y", "陈述"]
            elif pred in ("HAS", "BELONGS_TO"):
                patterns = ["X属于Y", "X是Y", "陈述"]
        elif action == "self_directed":
            patterns = ["陈述"]
        else:
            patterns = ["陈述", "X是Y"]
        return patterns

    def _query_language_traces(self, action: str, pred: str,
                                confidence_bucket: str) -> dict:
        """
        从 language_traces 原始语料中查询相似句子。

        不是查统计表——是查人类真实说过的句子。
        返回 {sentences: [...], top_openers: [...], top_closers: [...]}
        """
        if not self.star_map:
            return {}

        patterns = self._infer_pattern_types(action, pred)
        if not patterns:
            return {}

        # 找与当前场景句型相同的句子
        placeholders = ",".join("?" * len(patterns))
        rows = self.star_map.conn.execute(
            f"SELECT sentence, subj, pred, obj, pattern_type, sentence_type "
            f"FROM language_traces "
            f"WHERE pattern_type IN ({placeholders}) "
            f"ORDER BY CASE WHEN sentence_type='conversational' THEN 0 "
            f"WHEN sentence_type='encyclopedic' THEN 1 ELSE 2 END, "
            f"timestamp DESC LIMIT 30",
            patterns
        ).fetchall()

        if len(rows) < 2:
            return {}

        # 拆解每个句子 → 收集 opener 和 closer
        from collections import Counter
        openers = []
        closers = []
        sentences = []

        for row in rows:
            sentence = row[0]
            opener, _, closer = self._decompose_reply(sentence)
            if opener:
                openers.append(opener)
            if closer:
                closers.append(closer)
            sentences.append({
                "sentence": sentence,
                "subj": row[1], "pred": row[2], "obj": row[3],
                "pattern_type": row[4],
                "sentence_type": row[5] if len(row) > 5 else "unknown",
            })

        return {
            "sentences": sentences,
            "top_openers": Counter(openers).most_common(6),
            "top_closers": Counter(closers).most_common(4),
            "total": len(rows),
        }

    # ── v3.6: 关系驱动的叙事生成 ──
    def _compose_narrative(self, subj: str, activation: list[dict],
                            evidence: list) -> str | None:
        """
        v3.6 final: 边 → 关系模式 → 连���词链 → 一句话。

        不做独立从句拼接。先看所有显著边的类型组合，
        再找对应的连接词链，然后一次织成句子。
        """
        if not self.star_map or not subj or not activation:
            return None

        # ── 收集边 (目标, 关系类型) ──
        edges: list[tuple[str, str]] = []
        for a in activation[:5]:
            node = a["node"]
            for t in a.get("triggers", []):
                if t and len(t) >= 2 and "(" not in str(t) and "→" not in str(t):
                    edges.append((node, t))
                    break
            else:
                for row in self.star_map.conn.execute(
                    "SELECT relation FROM directed_edges WHERE source=? AND target=? LIMIT 1",
                    (subj, node)):
                    if row[0]: edges.append((node, row[0])); break

        if not edges: return None

        # ── 按关系类型分组，保留顺序 ──
        seen: list[str] = []
        grouped: dict[str, list[str]] = {}
        for target, rel in edges:
            if rel not in grouped:
                grouped[rel] = []; seen.append(rel)
            if target not in grouped[rel]:
                grouped[rel].append(target)

        if not seen: return None

        # ── 按"否定→分类→能力→食性→特征→栖息"固定顺序 ──
        order = {"NOT_CAN": 0, "NOT_IS_A": 0, "IS_A": 1, "CAN": 2, "EATS": 3, "HAS": 4, "ORBITS": 4, "LIVES_IN": 5}
        seen.sort(key=lambda r: order.get(r, 99))

        parts = []
        for rel in seen:
            targets = grouped[rel][:3]
            if rel in ("NOT_CAN", "NOT_IS_A"):
                parts.append(f"{'不会' if 'CAN' in rel else '不是'}{'、'.join(targets)}")
            elif rel == "IS_A":
                parts.append(f"属于{'、'.join(targets)}")
            elif rel == "CAN":
                parts.append(f"能{'、'.join(targets)}")
            elif rel == "HAS":
                parts.append(f"具有{'、'.join(targets)}")
            elif rel == "EATS":
                parts.append(f"吃{'、'.join(targets)}")
            elif rel == "LIVES_IN":
                parts.append(f"生活在{'、'.join(targets)}")

        if len(parts) == 1:
            return f"{subj}{parts[0]}。"

        # ── 根据首从句类型决定连接结构 ──
        first_rel = seen[0]
        if first_rel in ("NOT_CAN", "NOT_IS_A"):
            # "虽然不会X，但属于Y，能Z"
            sentence = f"{subj}虽然{parts[0]}"
            for i in range(1, len(parts)):
                p = parts[i]
                connector = "，但" if seen[i] == "IS_A" and i == 1 else "，还"
                sentence += f"{connector}{p}"
        else:
            sentence = f"{subj}{parts[0]}"
            for p in parts[1:]:
                sentence += f"，{p}"

        return sentence + "。"

        if len(clauses) < 2: return None

        # ── 用学来的连接词组合从句 (语言痕迹) ──
        rel_keys = [k for k in relations.keys() if k in ("IS_A","CAN","NOT_CAN","HAS","ORBITS","NOT_IS_A")]
        narrative = clauses[0]
        for i in range(1, len(clauses)):
            rel_a = rel_keys[i-1] if i-1 < len(rel_keys) else ""
            rel_b = rel_keys[i] if i < len(rel_keys) else ""
            conn = self.star_map.relation_connector(rel_a, rel_b) if self.star_map else "，"
            # 连接词本身已有过渡词汇（"属于，能"），直接接从句
            narrative += f"，{conn}{clauses[i]}" if conn != "。" else f"。{clauses[i]}"

        narrative += "。"
        if evidence: narrative += " 已确认「" + evidence[0][:80] + "」。"
        return narrative

    def _generate_from_traces(self, lt: dict, subj: str, pred: str, obj: str,
                               evidence: list, diffs: list, conf: float) -> str:
        """
        从原始语料的真实句子中生成回复。

        v3.5: 不只学开头标记，学整句的信息组织方式。
              提取句式骨架 → 填充当前实体 → 生成自然句子。
        """
        import random

        # ── 1. 找最匹配的句子 ──
        best_sentence = None
        for s in lt.get("sentences", []):
            sentence = s.get("sentence", "")
            if sentence.rstrip().endswith(('吗', '呢', '吧', '？', '?')):
                continue
            if s.get("subj") and s.get("pred") == pred:
                best_sentence = s
                break
        if not best_sentence:
            for s in lt.get("sentences", []):
                if not s.get("sentence","").rstrip().endswith(('吗','呢','吧','？','?')):
                    best_sentence = s
                    break
        if not best_sentence:
            best_sentence = lt["sentences"][0] if lt["sentences"] else None

        # ── 2. 提取句式骨架 ──
        if best_sentence:
            skeleton = self._extract_sentence_skeleton(
                best_sentence["sentence"], best_sentence.get("subj",""),
                best_sentence.get("obj",""), pred)
        else:
            skeleton = None

        # ── 3. 填充当前实体 → 生成 ──
        if skeleton and skeleton.get("usable"):
            body = self._fill_skeleton(skeleton, subj, pred, obj, evidence, conf)
            return body
        else:
            # 回退: 用 opener marker
            openers = lt.get("top_openers", [])
            if not openers:
                return self._fallback_template(
                    "info_request", subj, pred, obj, conf, evidence, diffs, "")
            chosen_opener = openers[0][0]
            marker = self._extract_opener_marker(chosen_opener)
            if evidence:
                body = "「" + evidence[0] + "」"
            else:
                body = f"{subj} {pred} {obj}"
            return f"{marker}{body}"

    def _extract_sentence_skeleton(self, sentence: str, orig_subj: str,
                                    orig_obj: str, pred: str) -> dict:
        """
        v3.5: 从一句话中提取句式骨架。

        不是找开头几个字——是提取整句的信息组织方式:
          {subj} 有 X 的美称，是一种 Y
          {subj} 不是 {obj}，因为 {reason}
          {subj} 满足 {obj} 的特征：{features}

        返回 {usable, template, clause_count, length}
        """
        # 按标点拆从句
        clauses = re.split(r'[，,；;]', sentence)
        clauses = [c.strip() for c in clauses if c.strip()]

        if not clauses:
            return {"usable": False}

        # 生成模板: 用占位符替换原实体
        template_parts = []
        for clause in clauses:
            c = clause
            if orig_subj and orig_subj in c:
                c = c.replace(orig_subj, "{subj}")
            if orig_obj and orig_obj in c:
                c = c.replace(orig_obj, "{obj}")
            template_parts.append(c)

        template = "，".join(template_parts)

        # 可用的骨架: 至少替换了一个实体 + 长度合理
        usable = ("{subj}" in template or "{obj}" in template) and len(template) > 4

        return {
            "usable": usable,
            "template": template,
            "clause_count": len(clauses),
            "length": len(sentence),
            "original": sentence,
        }

    def _fill_skeleton(self, skeleton: dict, subj: str, pred: str, obj: str,
                        evidence: list, conf: float) -> str:
        """
        用当前实体填充句式骨架。
        """
        template = skeleton["template"]
        result = template.replace("{subj}", subj).replace("{obj}", obj)

        # 如果有证据，附上
        if evidence:
            result += "「" + evidence[0] + "」"

        return result

    def _extract_opener_marker(self, opener: str) -> str:
        """
        从语料句子开头提取纯语气标记。

        "对的，企鹅是鸟类" → "对的，"
        "嗯，猫确实属于哺乳动物" → "嗯，"
        "没错，海豚是一种哺乳动物" → "没错，"
        "✅ 学到了: 猫 IS_A 哺乳动物" → "✅ 学到了: "
        """
        # 已知的语气标记模式
        markers = [
            r'^对的[，,]\s*',
            r'^不对[，,]\s*',
            r'^嗯[，,]\s*',
            r'^没错[，,]\s*',
            r'^是的[，,]\s*',
            r'^对[，,]\s*',
            r'^所以[，,]\s*',
            r'^那[，,]\s*',
            r'^应该对[，,——\s]*',
            r'^好[的][，,]\s*',
            r'^✅\s*学到了[：:]\s*',
            r'^我刚查了一下[——\s]*',
        ]
        for pat in markers:
            m = re.match(pat, opener)
            if m:
                return m.group(0)
        # 没有匹配到已知标记: 返回前几个字
        return opener[:min(6, len(opener))]

    def _generate_from_corpus(self, patterns: list[dict],
                               subj: str, pred: str, obj: str,
                               evidence: list, diffs: list,
                               conf: float, action: str) -> str:
        """从统计候选中加权选择组件, 组装句子"""
        # 加权选择 opener
        total_count = sum(p["count"] for p in patterns)
        if total_count > 0:
            r = random.random() * total_count
            cumulative = 0
            chosen = patterns[0]  # fallback
            for p in patterns:
                cumulative += p["count"]
                if r <= cumulative:
                    chosen = p
                    break
        else:
            chosen = patterns[0]

        opener = chosen["opener"]
        closer = chosen["closer"]

        # 填充 body: 用实体替换 body_template 中的占位符
        body = self._fill_body(chosen["body_template"],
                               subj, pred, obj, evidence, diffs, conf)

        # 填充 closer 中的占位符
        closer = closer.replace("{conf}", f"{conf:.0%}")

        return f"{opener}{body}{closer}"

    def _fill_body(self, template: str, subj: str, pred: str, obj: str,
                    evidence: list, diffs: list, conf: float) -> str:
        """用实体填充 body 模板"""
        # 如果有具体证据, 填充; 否则用简洁形式
        if evidence:
            ev_text = "「" + evidence[0] + "」"
            if len(evidence) > 1:
                ev_text += f" 和 「{evidence[1]}」"
            body = template.replace("{evidence}", ev_text)
        else:
            body = template.replace("{evidence}", f"{subj} {pred} {obj}")
        body = body.replace("{subj}", subj)
        body = body.replace("{pred}", pred)
        body = body.replace("{obj}", obj)
        body = body.replace("{conf}", f"{conf:.0%}")
        return body

    # ── 模板回退 ──

    def _fallback_template(self, action: str, subj: str, pred: str, obj: str,
                            conf: float, evidence: list, diffs: list,
                            source: str) -> str:
        """冷启动回退——与原 _structure_to_language 等价"""

        if action == "fact_learn":
            parts = [f"✅ 学到了: {subj}"]
            if pred:
                parts.append(pred)
            if obj:
                parts.append(obj)
            return " ".join(parts)

        if action == "info_request":
            if not evidence:
                return f"关于「{subj}」我还不了解。你能教我吗?"
            if source == "online_learning":
                parts = [f"我刚查了一下——"]
                ev_short = evidence[:2]
                parts.append(f"「{ev_short[0]}」")
                if len(ev_short) > 1:
                    parts.append(f"，还有「{ev_short[1]}」")
                parts.append(f"。(置信 {conf:.0%})")
                return " ".join(parts)
            if source == "knowledge_gap":
                return f"关于「{subj}」和「{obj}」的关系，我查了但没找到可靠信息。你能教我吗?"
            if conf > 0.5:
                head = "对" if conf > 0.7 else "应该对"
                parts = [f"{head}——"]
                ev_short = evidence[:2]
                parts.append(f"比如「{ev_short[0]}」")
                if len(ev_short) > 1:
                    parts.append(f"和「{ev_short[1]}」都知道;")
                if diffs:
                    parts.append(f"但{diffs[0]}不同。")
                parts.append(f"(置信 {conf:.0%})")
                return " ".join(parts)
            elif conf > 0.3:
                return f"不太确定——关于「{subj}」和「{obj}」的关系。你能确认吗?"
            else:
                return f"关于「{subj}」我还不知道。你能教我吗?"

        if action == "self_directed":
            return f"我是 AsteriaMind。{evidence[0] if evidence else ''}"

        if action in ("uncertain", "observe"):
            # ── v3.5: 能量感知的不确定表达 ──
            # 不是死板的"试试说X是Y"——而是告诉用户: 我的星图里这个区域是暗的
            if subj:
                return (f"我的认知网里没有捕获到「{subj}」的高亮信号——"
                        f"你在谈论一个全新的概念吗？")
            return "我没有捕获到清晰的信号。你能换个方式描述吗？"

        return f"[{action}] {subj} {pred} {obj}"

    # ── 辅助 ──

    def _confidence_bucket(self, conf: float) -> str:
        if conf > 0.7:
            return "high"
        elif conf > 0.3:
            return "medium"
        return "low"

    def _decompose_reply(self, reply: str) -> tuple[str, str, str]:
        """
        把完整回复拆解为 opener + body + closer。

        启发式:
          - opener: 第一个「或实体引用之前的文本
          - closer: 最后一个括号内容或句末标点后的内容
          - body: 中间部分
        """
        # 找 opener 结束位置
        opener_end = 0

        # 常见 opener 模式
        opener_patterns = [
            r'^(✅\s*学到了:|我刚查了一下——|对——|应��对——)',
            r'^关于「.+?」我',
            r'^(不太确定|我不太确定)',
            r'^我是 AsteriaMind',
        ]
        for pat in opener_patterns:
            m = re.match(pat, reply)
            if m:
                opener_end = m.end()
                break
        if opener_end == 0:
            # 找第一个 emoji 或标点
            m = re.match(r'^([^「\u4e00-\u9fff]*?)["「]', reply)
            if m:
                opener_end = m.start(2) if m.lastindex and m.lastindex >= 2 else m.end(1)

        # 找 closer 起始位置
        closer_start = len(reply)
        closer_patterns = [
            r'\(置信 \d+%\)$',
            r'。你能教我吗\?$',
            r'。需要我查一下吗\?$',
            r'——你能帮我确认吗\?$',
            r'。(置信 \d+%)$',
        ]
        for pat in closer_patterns:
            m = re.search(pat, reply)
            if m:
                closer_start = m.start()
                break

        opener = reply[:opener_end].strip()
        body = reply[opener_end:closer_start].strip()
        closer = reply[closer_start:].strip()

        if not opener:
            opener = reply[:min(10, len(reply))].strip()
            body = reply[min(10, len(reply)):].strip()
            closer = ""

        return opener, body, closer

    def _feed_word_cooccur(self, opener: str, body: str, closer: str,
                            subj: str, pred: str, obj: str, ctx: str):
        """喂入词级共现数据"""
        star = self.star_map

        # opener 与 body 开头的共现: 提取干净词
        if opener and body:
            opener_clean = re.sub(r'[：:✅📝💡\s]', '', opener).strip()
            body_clean = re.sub(r'[「」\s]', '', body).strip()
            if opener_clean and body_clean:
                star.learn_word_cooccur(opener_clean[-4:], body_clean[:4], "bigram", ctx)
            # 同时也喂关键词
            for kw in re.findall(r'[\u4e00-\u9fff]{2,}', opener):
                for kw2 in re.findall(r'[\u4e00-\u9fff]{2,}', body)[:2]:
                    star.learn_word_cooccur(kw, kw2, "bigram", ctx)

        # body 内实体的共现
        if subj and pred:
            star.learn_word_cooccur(subj, pred, "entity_rel", ctx)
        if pred and obj:
            star.learn_word_cooccur(pred, obj, "entity_rel", ctx)

        # closer 与其前文的共现
        if closer and body:
            body_clean = re.sub(r'[「」\s]', '', body).strip()
            closer_clean = re.sub(r'[：:✅📝💡\s]', '', closer).strip()
            if body_clean and closer_clean:
                star.learn_word_cooccur(body_clean[-4:], closer_clean[:4], "bigram", ctx)
            # 关键词共现
            for kw in re.findall(r'[\u4e00-\u9fff]{2,}', closer):
                for kw2 in re.findall(r'[\u4e00-\u9fff]{2,}', body)[-2:]:
                    star.learn_word_cooccur(kw, kw2, "bigram", ctx)

    def seed_corpus_from_templates(self):
        """
        冷启动种子: 把当前模板的变体喂入语料库。

        只需调用一次——让语料库从空开始时有基本数据。
        """
        if not self.star_map:
            return

        seeds = [
            # (action, bucket, source, opener, body, closer)
            ("fact_learn", "high", "", "✅ 学到了: ",
             "{subj} {pred} {obj}", ""),
            ("fact_learn", "medium", "", "📝 记录了: ",
             "{subj} {pred} {obj}", ""),
            ("info_request", "high", "",
             "对——", "比如{evidence}都知道;", " (置信 {conf})"),
            ("info_request", "high", "",
             "应该对——", "根据已有知识，{evidence}", " (置信 {conf})"),
            ("info_request", "medium", "",
             "应该对——", "比如{evidence}都知道;", " (置信 {conf})"),
            ("info_request", "medium", "",
             "不太确定——", "关于「{subj}」和「{obj}」的关系", "。你能确认吗?"),
            ("info_request", "low", "",
             "关于「{subj}」", "我还不了解。", "你能教我吗?"),
            ("info_request", "high", "online_learning",
             "我刚查了一下——", "「{evidence}」", "。(置信 {conf})"),
            ("info_request", "medium", "knowledge_gap",
             "关于「{subj}」和「{obj}」的关系，",
             "我查了但没找到可靠信息。", "你能教我吗?"),
            ("self_directed", "medium", "",
             "我是 AsteriaMind。", "{evidence}", ""),
        ]

        for action, bucket, source, opener, body, closer in seeds:
            self.star_map.learn_expression_pattern(
                action, bucket, source, opener, body, closer)
