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
                search_result = self.web_search.search(f"{word} 定义", max_results=4)
                # ★ v3.6: 相关性校验 — snippet/title 必须包含查询词, 否则是垃圾结果
                for r in search_result:
                    if not r.snippet or "未连接" in r.snippet:
                        continue
                    # 查询词相关性: title 或 snippet 含 word 或其 2 字片段
                    hit = word in (r.title + r.snippet)
                    if not hit and len(word) >= 2:
                        hit = word[:2] in (r.title + r.snippet)
                    if not hit:
                        continue  # 电视剧/广告 → 拒绝
                    result["known"] = True
                    result["definition"] = r.snippet[:200]
                    result["confidence"] = 0.5
                    result["source"] = "web_search"
                    # 存入 KG
                    if self.kg:
                        self.kg.add(word, "MEANS", r.snippet[:100],
                                   confidence=0.5, source="web_search")
                    # ★ v3.5: 能量扩散写入 — 搜索结果直接增强共现网
                    if self.star_map:
                        self.star_map.spread_write(r.snippet)
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
        all_search_results = []  # ★ 收集所有原始搜索结果
        for query in queries:
            if not self.web_search:
                break
            try:
                search_results = self.web_search.search(query, max_results=3)
                all_search_results.extend(search_results)
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

        # 4. 存入星图 (三元组 + 原始句子)
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

            # ★ v3.5: 搜索结果原始句子 → language_traces + 能量扩散写入
            self._store_search_sentences(all_search_results, subj, pred, obj)

            # 能量扩散: 搜索结果中提取高频实词 → 两两建立共现连接
            for r_item in all_search_results:
                snippet = r_item.snippet if hasattr(r_item, 'snippet') else ""
                if snippet and len(snippet) > 10:
                    self.star_map.spread_write(snippet)

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

    def _store_search_sentences(self, search_results: list,
                                 subj: str, pred: str, obj: str):
        """
        v3.5: 把搜索结果的原始句子存入 language_traces 作为表达语料。

        这解决了"小冰/小爱能学会说话，AM 为什么不行?"的问题——
        她们从网络文本中学自然表达，我们现在也从搜索结果中学。

        只存包含查询实体的句子，避免噪声。
        """
        if not self.star_map:
            return
        stored = 0
        for r in search_results:
            snippet = r.snippet if hasattr(r, 'snippet') else ""
            if not snippet:
                continue
            if any(m in snippet for m in ("搜索未返回", "需WebSearch", "搜索不可用", "搜索异常")):
                continue
            # 按标点分句
            for sent in re.split(r'[。.！!？?\n\r]+', snippet):
                sent = sent.strip()
                if len(sent) < 8:
                    continue
                # 只存包含查询实体的句子
                if subj not in sent:
                    continue
                pattern = self.star_map._language_pattern(sent)
                stype = self.star_map._tag_sentence_type(sent)
                try:
                    self.star_map.conn.execute(
                        "INSERT INTO language_traces"
                        "(sentence,subj,pred,obj,cognitive_id,pattern_type,sentence_type,timestamp) "
                        "VALUES(?,?,?,?,NULL,?,?,?)",
                        (sent, subj, pred, obj, pattern, stype, time.time()))
                    stored += 1
                except Exception:
                    pass
        if stored:
            self.star_map.conn.commit()

    def _extract_facts(self, subj: str, pred: str, obj: str,
                       snippet: str) -> list[dict]:
        """
        从搜索结果 snippet 中提取结构化知识。

        v3.4: 广谱学习 — 不按查询相关性过滤, 接受所有结构合法的三元组。
              垃圾过滤靠实体质量而非相关性。
        """
        facts = []

        # ── 扩展停用词: 只过滤真正的代词/连词/副词碎片 ──
        _skip_s = {
            # 代词
            '这', '那', '它', '他', '她', '我', '你',
            '它们', '他们', '她们', '我们', '你们',
            '这些', '那些', '什么', '谁', '哪', '其',
            # 连词/副词 (正则碎片常见)
            '但', '而', '就', '都', '也', '还', '可', '很', '不', '是',
            '所以', '因为', '即便', '即使', '当然', '可能', '毫无疑问', '其实',
            '这就', '那就', '却是', '便是',
            # 断句残片
            '期', '前', '后', '的',
        }
        _skip_o = {
            '什么', '怎么', '为什么', '这样', '那样', '一个', '吗', '呢', '哪',
        }

        # ── 实体质量检查 ──
        def _clean_entity(e: str) -> str:
            """清洗实体: 去前导数字和标点"""
            return re.sub(r'^[\d\s\W_]+', '', e).strip()

        def _valid_subject(s: str) -> bool:
            """主体是否像一个真正的实体? 排除代词/连词/碎片"""
            s = _clean_entity(s)
            if not s or len(s) < 2:
                return False
            if s in _skip_s:
                return False
            # 必须包含至少一个中文
            if not any('\u4e00' <= c <= '\u9fff' for c in s):
                return False
            # 不能以常见副词/连词开头
            _bad_starts = {'就', '都', '也', '还', '可', '很', '但', '而', '不',
                           '所以', '因为', '即便', '即使', '当然', '可能', '其实',
                           '期', '主要', '多数', '少数', '其次', '另外', '此外',
                           '最初', '最早', '最后', '最终', '首先', '然后',
                           '认为', '或许', '也许', '大概', '大约', '一般',
                           '以及', '并且', '或者', '还是',
                           '美称', '言企', '每只', '每个', '一种',
                           '它的', '他的', '她的', '我的', '你的',
                           '其是', '则是', '便是', '就是',
                           '什么', '怎么', '为什么', '如何',
                           }
            for bs in sorted(_bad_starts, key=len, reverse=True):
                if s.startswith(bs):
                    return False
            # 不能以常见代词开头
            if any(s.startswith(p) for p in ('它们', '我们', '你们', '他们', '她们', '自己')):
                return False
            # 不能以中文单前缀开头 (搜索片段截断痕迹)
            if s.startswith('乳') or s.startswith('学'):
                return False
            if '的' in s:
                return False
            return True

        def _valid_object(o: str) -> bool:
            """客体是否合法? 排除问句和碎片"""
            o = _clean_entity(o)
            if not o or len(o) < 2:
                return False
            if o in _skip_o:
                return False
            if o.endswith('吗') or o.endswith('呢') or o.endswith('吧') or o.endswith('么'):
                return False
            if '什么' in o or '怎么' in o or '为什么' in o:
                return False
            # 不能是 "不是X" 或 "没有X" 形式 (否定应该在谓词, 不在客体)
            if o.startswith('不') or o.startswith('没'):
                return False
            return True

        def _valid_object(o: str) -> bool:
            """客体是否合法? 排除问句和碎片"""
            o = o.strip()
            if not o or len(o) < 2:
                return False
            if o in _skip_o:
                return False
            # 不能是问句
            if o.endswith('吗') or o.endswith('呢') or o.endswith('吧'):
                return False
            if '什么' in o or '怎么' in o or '为什么' in o:
                return False
            return True

        # 按标点分句
        sentences = re.split(r'[，,。.；;！!？?、\n\r]+', snippet)
        last_subj = None

        for sent in sentences:
            sent = sent.strip()
            if not sent or len(sent) < 2:
                continue

            # "X不是Y" → NOT_IS_A (先于"是"处理)
            for m in re.finditer(
                r'([\u4e00-\u9fff\w]{2,8})不是([\u4e00-\u9fff\w]{1,18})', sent):
                s, o = _clean_entity(m.group(1)), _clean_entity(m.group(2))
                if _valid_subject(s) and _valid_object(o):
                    facts.append({"subj": s, "pred": "NOT_IS_A", "obj": o})
                    last_subj = s
            # 以 "不是" 开头 → 继承前文主语
            if last_subj and sent.startswith('不是'):
                m = re.match(r'不是([\u4e00-\u9fff\w]{1,18})', sent)
                if m:
                    o = _clean_entity(m.group(1))
                    if _valid_object(o):
                        facts.append({"subj": last_subj, "pred": "NOT_IS_A",
                                      "obj": o})

            # "X是Y" → IS_A
            for m in re.finditer(
                r'([\u4e00-\u9fff\w]{2,8})(?<!不)是([\u4e00-\u9fff\w]{1,18})', sent):
                s, o = _clean_entity(m.group(1)), _clean_entity(m.group(2))
                if _valid_subject(s) and _valid_object(o):
                    facts.append({"subj": s, "pred": "IS_A", "obj": o})
                    last_subj = s

            # "X属于Y" → BELONGS_TO
            for m in re.finditer(
                r'([\u4e00-\u9fff\w]{2,8})属于([\u4e00-\u9fff\w]{1,18})', sent):
                s, o = _clean_entity(m.group(1)), _clean_entity(m.group(2))
                if _valid_subject(s) and _valid_object(o):
                    facts.append({"subj": s, "pred": "BELONGS_TO", "obj": o})
                    last_subj = s

            # "X会Y" / "X能Y" / "X可以Y" → CAN
            for m in re.finditer(
                r'([\u4e00-\u9fff\w]{2,8})(?<!不)(?:会|能|可以)([\u4e00-\u9fff\w]{1,18})', sent):
                s, o = _clean_entity(m.group(1)), _clean_entity(m.group(2))
                if _valid_subject(s) and _valid_object(o):
                    facts.append({"subj": s, "pred": "CAN", "obj": o})
                    last_subj = s

        # ── 去重: 同一三元组只保留一次 ──
        seen = set()
        unique = []
        for f in facts:
            key = (f["subj"], f["pred"], f["obj"])
            if key not in seen:
                seen.add(key)
                unique.append(f)
        return unique
