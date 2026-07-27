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

        核心逻辑: 查语料库 → 有足够的统计 → 用统计驱动生成
                                → 不足 → 回退模板
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

        # ── 尝试语料库驱动 ──
        if self.star_map:
            patterns = self.star_map.query_expression_patterns(
                action, bucket, source, min_count=2, top_k=5)
            if patterns and len(patterns) >= 2:
                # 语料库足够 → 统计驱动
                return self._generate_from_corpus(
                    patterns, subj, pred, obj, evidence, diffs, conf, action)

        # ── 回退模板 ──
        return self._fallback_template(
            action, subj, pred, obj, conf, evidence, diffs, source)

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

    # ── 语料库驱动生成 ──

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
