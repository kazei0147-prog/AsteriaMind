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

        # ── 守卫: 非实体输入 / 非询问动作 → 直接走模板 ──
        # 防止 "hello"、"嗯"、"哈哈" 被强行塞进学习到的句子骨架
        if not self._looks_like_entity(subj):
            return self._fallback_template(
                action, subj, pred, obj, conf, evidence, diffs, source)
        if action not in ("info_request", "fact_learn"):
            return self._fallback_template(
                action, subj, pred, obj, conf, evidence, diffs, source)

        # ── 1. language_traces 原始语料: 从真实句子里学表达 ──
        if self.star_map:
            lt = self._query_language_traces(action, pred, bucket)
            if lt and len(lt.get("sentences", [])) >= 2:
                result = self._generate_from_traces(
                    lt, subj, pred, obj, evidence, diffs, conf)
                # 兜底: 骨架生成结果如果还是不像话 (含未替换占位符或太短), 走模板
                if result and "{subj}" not in result and "{obj}" not in result \
                        and len(result) >= 4:
                    return result

            # ── 2. lang_patterns 统计抽象 ──
            patterns = self.star_map.query_expression_patterns(
                action, bucket, source, min_count=2, top_k=5)
            if patterns and len(patterns) >= 2:
                return self._generate_from_corpus(
                    patterns, subj, pred, obj, evidence, diffs, conf, action)

        # ── 3. 模板回退 ──
        return self._fallback_template(
            action, subj, pred, obj, conf, evidence, diffs, source)

    def _looks_like_entity(self, s: str) -> bool:
        """
        v3.5: 判断字符串是否像实体 (主语/宾语)。

        防止 "hello"/"嗯"/"哈哈" 等非实体词被填进学习到的句子骨架。
        """
        if not s or len(s) < 2:
            return False
        # 必须是包含中文的字符串
        if not any('\u4e00' <= c <= '\u9fff' for c in s):
            return False
        # 不能是纯语气词/代词
        _stop = {'这', '那', '它', '他', '她', '我', '你', '什么', '怎么',
                 '嗯', '啊', '哦', '唉', '哈', '嘿嘿', '哈哈', '哈哈',
                 '哦哦', '哦哈', '呵呵', '嗯嗯', '好的', '是的', '对的'}
        if s in _stop:
            return False
        # 不能含问号
        if '?' in s or '?' in s:
            return False
        # 不能含"哈哈""嘻嘻"等纯笑声
        if any(laugh in s for laugh in ('哈哈', '嘻嘻', '呵呵', '嘿嘿')):
            return False
        # 不能太短 (单字)
        if len(s) < 2:
            return False
        return True

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
            return f"我不太确定你的意思。试试说「X是Y」或「X会Y吗」?"

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
