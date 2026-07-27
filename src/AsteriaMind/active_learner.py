"""
ActiveLearner — AM 的主动学习 + 语言习得能力 (AsteriaMind v3.2)

不是被动接收。是主动发现缺口、主动提问。

核心循环:
  1. 遇到未知 → 先查 KG → 再试 Skill → 搜网络 → 最后提问用户
  2. 语言习得: 词汇/语法/翻译 → 存入 KG → 向量化 → 跨语言类比
  3. 问题队列: 攒够一批再问, 不逐条打断
"""
import re, time
from typing import Optional, List


class ActiveLearner:
    """
    主动学习者——不知道就查, 查不到就问。

    不是 LLM 那种"猜一个"。是"我不知道, 让我想办法知道"。
    """

    def __init__(self, kg=None, vl=None, web_search=None, cmd_tool=None, star_map=None):
        self.kg = kg
        self.vl = vl
        self.web_search = web_search
        self.cmd = cmd_tool
        self.star_map = star_map
        self.pending_questions: list[dict] = []  # 待提问用户的问题

    def learn_word(self, word: str, lang: str = "zh") -> dict:
        """
        学习一个词: 查 StarMap → 查 KG → 查向量 → 搜网络 → 问用户。

        返回 {word, known, definition, source, confidence}
        """
        result = {"word": word, "lang": lang, "known": False}

        # 0. 查 StarMap (v3 认知空间 — 优先!)
        if self.star_map and hasattr(self.star_map, 'conn'):
            try:
                for row in self.star_map.conn.execute(
                    "SELECT pred, obj FROM cognitive_traces "
                    "WHERE subj=? AND feedback='confirmed' LIMIT 5", (word,)):
                    result["known"] = True
                    result["definition"] = f"{row[0]} {row[1]}"
                    result["confidence"] = 0.7
                    result["source"] = "star_map"
                    return result
            except Exception:
                pass

        # 1. 查 KG (legacy 兼容)
        if self.kg:
            for r in self.kg.relations:
                if r.subject == word:
                    if r.predicate in ("IS_A", "MEANS", "TRANSLATES_TO", "HAS_MEANING"):
                        result["known"] = True
                        result["definition"] = r.object
                        result["confidence"] = r.confidence
                        result["source"] = "kg_cache"
                        return result

        # 2. 查向量 (语义相似: 不认识但可能认识类似的?)
        if self.vl:
            similar = self.vl.search(word, top_k=3, min_similarity=0.3)
            if similar:
                result["hints"] = [(k, s) for k, s, _ in similar]
                result["note"] = "向量空间有相似概念，但无精确匹配"

        # 3. 搜网络
        if self.web_search:
            try:
                search_result = self.web_search.search(f"{word} 定义", max_results=2)
                for r in search_result:
                    if r.snippet and "未连接" not in r.snippet:
                        result["known"] = True
                        result["definition"] = r.snippet[:200]
                        result["confidence"] = 0.5
                        result["source"] = "web_search"
                        # 存入 KG
                        if self.kg:
                            self.kg.add(word, "MEANS", r.snippet[:100],
                                       confidence=0.5, source="web_search")
                        return result
            except Exception:
                pass

        # 4. 都不行 → 问用户
        self.pending_questions.append({
            "word": word, "context": f"不认识 '{word}'，KG/向量/网络均未找到",
            "timestamp": time.time(),
        })

        result["pending"] = True
        result["note"] = "已加入提问队列，等待用户解答"
        return result

    def learn_from_text(self, text: str) -> dict:
        """
        从一段文本中学习。分词 → 对每个不认识的字提问。

        不是一次性全吞——不认识的才问。
        """
        # 简单分词: 中文按字+词, 英文按空格
        words = []
        # 英文词
        words.extend(re.findall(r'[a-zA-Z]{3,}', text.lower()))
        # 中文双字
        cn = re.sub(r'[a-zA-Z0-9\s]+', '', text)
        for i in range(len(cn) - 1):
            words.append(cn[i:i+2])

        results = []
        for w in set(words[:20]):  # 最多 20 个不同词
            r = self.learn_word(w)
            if not r.get("known"):
                results.append(r)

        return {
            "total_words": len(words),
            "unique": len(set(words)),
            "known": len(results) == 0,
            "unknown": len(results),
            "pending_questions": [r["word"] for r in results if r.get("pending")],
        }

    def ask_user(self, question: str, context: str = "") -> dict:
        """
        主动提问用户。

        不打断——加入队列, 等待合适时机一并呈现。
        """
        self.pending_questions.append({
            "question": question,
            "context": context,
            "timestamp": time.time(),
        })
        return {"queued": True, "position": len(self.pending_questions)}

    def get_questions(self, max_q: int = 5) -> List[dict]:
        """取出待提问的问题 (不清除, 回答后由外部清除)"""
        return self.pending_questions[-max_q:]

    def answer_question(self, word: str, answer: str, confidence: float = 0.8):
        """用户回答了问题 → 存入 KG"""
        if self.kg:
            self.kg.add(word, "MEANS", answer, confidence=confidence,
                       source="user_taught")
        # 清除对应的 pending
        self.pending_questions = [
            q for q in self.pending_questions
            if q.get("word") != word and word not in q.get("question", "")
        ]
        return {"learned": word, "answer": answer}

    # ═══════════════════════════════════════
    #  在线学习: learn_relation
    # ═══════════════════════════════════════

    def learn_relation(self, subj: str, pred: str, obj: str) -> dict:
        """
        在线学习: 针对一个三元组查询外部信息。

        流程:
          1. 先查 StarMap 是否已有足够证据
          2. 根据三元组结构生成搜索查询
          3. 搜网络
          4. 从搜索结果提取结构化知识
          5. 存入星图 (source=online_learning)
          6. 搜不到 → 加入提问队列

        返回 {subject, predicate, object, learned, source, facts}
        """
        result = {"subject": subj, "predicate": pred, "object": obj,
                  "learned": False, "source": "none"}

        # 1. 先查星图 — 有直接证据就不用搜
        if self.star_map and hasattr(self.star_map, 'conn'):
            try:
                direct = list(self.star_map.conn.execute(
                    "SELECT feedback FROM cognitive_traces "
                    "WHERE subj=? AND pred=? AND obj=? AND feedback='confirmed'",
                    (subj, pred, obj)
                ))
                if direct:
                    result["known"] = True
                    result["source"] = "star_map"
                    result["confidence"] = 0.8
                    result["evidence_count"] = len(direct)
                    return result
            except Exception:
                pass

        # 2. 生成搜索查询
        queries = self._generate_search_queries(subj, pred, obj)

        # 3. 搜网络
        learned_facts = []
        for query in queries:
            if not self.web_search:
                break
            try:
                search_results = self.web_search.search(query, max_results=3)
                for r in search_results:
                    snippet = r.snippet or ""
                    # 过滤占位符结果
                    if any(marker in snippet for marker in
                           ("搜索未返回", "需WebSearch", "搜索不可用", "搜索结果:")):
                        continue
                    # 从 snippet 提取知识
                    facts = self._extract_facts(subj, pred, obj, snippet)
                    for f in facts:
                        f["source_query"] = query
                    learned_facts.extend(facts)
            except Exception:
                pass

        # 4. 存入星图
        if learned_facts and self.star_map:
            seen = set()
            for fact in learned_facts:
                key = f"{fact['subj']}::{fact['pred']}::{fact['obj']}"
                if key in seen:
                    continue
                seen.add(key)
                self.star_map.store(
                    fact["subj"], fact["pred"], fact["obj"],
                    "confirmed",
                    f"online_learning: {fact.get('source_query', '')[:40]}"
                )
            result["learned"] = True
            result["source"] = "web_search"
            result["facts"] = learned_facts
            result["fact_count"] = len(seen)
            return result

        # 5. 搜不到 → 问用户
        self.pending_questions.append({
            "word": subj,
            "context": f"在线学习: {subj} {pred} {obj} — 网络搜索未找到可靠信息",
            "timestamp": time.time(),
        })
        result["pending"] = True
        result["note"] = "已加入提问队列，等待用户解答"
        return result

    def _generate_search_queries(self, subj: str, pred: str, obj: str) -> list[str]:
        """根据三元组结构生成搜索查询"""
        queries = []
        if pred == "IS_A":
            queries.append(f"{subj} 是什么 分类")
            if obj:
                queries.append(f"{subj} 是{obj}吗")
                queries.append(f"{obj} 特征 定义")
        elif pred == "CAN":
            queries.append(f"{subj} 能力 特征")
            if obj:
                queries.append(f"{subj} 会{obj}吗")
        elif pred == "CAUSES":
            queries.append(f"{subj} {obj} 原因 因果")
        elif pred == "ORBITS":
            queries.append(f"{subj} 围绕 {obj} 运行")
        elif pred == "HAS":
            queries.append(f"{subj} 有{obj}吗 特征")
        else:
            queries.append(f"{subj} {obj} 是什么")
        return queries

    def _extract_facts(self, subj: str, pred: str, obj: str,
                       snippet: str) -> list[dict]:
        """从搜索结果 snippet 中提取结构化知识"""
        facts = []
        skip_s = ('这', '那', '它', '他', '她', '我', '你', '什么', '一个', '我们', '你们', '不', '是', '但')
        skip_o = ('什么', '怎么', '为什么', '这样', '那样', '一个')

        # 按标点分句
        sentences = re.split(r'[，,。.；;！!？?、\n\r]+', snippet)
        last_subj = None

        for sent in sentences:
            sent = sent.strip()
            if not sent or len(sent) < 2:
                continue

            # "X不是Y" → NOT_IS_A (先于"是"处理, 避免误匹配)
            for m in re.finditer(
                r'([\u4e00-\u9fff\w]{2,8})不是([\u4e00-\u9fff\w]{1,15})', sent):
                s, o = m.group(1).strip(), m.group(2).strip()
                if s not in skip_s:
                    facts.append({"subj": s, "pred": "NOT_IS_A", "obj": o})
                    last_subj = s
            # 以 "不是" 开头 → 继承前文主语
            if last_subj and sent.startswith('不是'):
                m = re.match(r'不是([\u4e00-\u9fff\w]{1,15})', sent)
                if m:
                    facts.append({"subj": last_subj, "pred": "NOT_IS_A",
                                  "obj": m.group(1).strip()})

            # "X是Y" → IS_A (负向后顾: 排除"不是"里的"是")
            for m in re.finditer(
                r'([\u4e00-\u9fff\w]{2,8})(?<!不)是([\u4e00-\u9fff\w]{1,15})', sent):
                s, o = m.group(1).strip(), m.group(2).strip()
                if s in skip_s or o in skip_o:
                    continue
                if '不' in s or '但' in s:
                    continue
                facts.append({"subj": s, "pred": "IS_A", "obj": o})
                last_subj = s

            # "X属于Y" → BELONGS_TO
            for m in re.finditer(
                r'([\u4e00-\u9fff\w]{2,8})属于([\u4e00-\u9fff\w]{1,15})', sent):
                s, o = m.group(1).strip(), m.group(2).strip()
                if s in skip_s:
                    continue
                facts.append({"subj": s, "pred": "BELONGS_TO", "obj": o})
                last_subj = s

            # "X会Y" / "X能Y" → CAN (负向后顾: 排除"不会"里的"会")
            for m in re.finditer(
                r'([\u4e00-\u9fff\w]{2,8})(?<!不)(?:会|能|可以)([\u4e00-\u9fff\w]{1,15})', sent):
                s, o = m.group(1).strip(), m.group(2).strip()
                if s in skip_s or '不' in s or '但' in s:
                    continue
                facts.append({"subj": s, "pred": "CAN", "obj": o})
                last_subj = s

        return facts
