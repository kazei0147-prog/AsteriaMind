"""
Cognitive Interface Layer — AM 的感觉器官 (AsteriaMind v3.2)

不是"输入分类器"。
是外部人类语言 ↔ 内部符号认知的神经桥接。

架构:
  Input
    ↓
  SemanticHypothesisEngine  ("他说了什么?")
    ↓
  PragmaticIntentEngine     ("为什么说?")
    ↓
  ActionIntentEngine        ("执行什么动作?")
    ↓
  Cognitive Core (KG / MH / WorldModel)

三层共享 MH 的 BudgetContest→scoring→falsification 机制,
但 Registry 独立分离:
  - WorldHypothesisRegistry
  - SemanticPatternRegistry
  - PragmaticIntentRegistry

7 个最小语言原语:
  Entity | Relation | Attribute | Time | Question | Negation | Perspective
"""
import re
from dataclasses import dataclass, field
from typing import Optional


# ═══════════════════════════════════════
#  最小语言原语
# ═══════════════════════════════════════

@dataclass
class LanguagePrimitive:
    """一个语言原子——AM 不需要被教语法，她用这些原子自己去发现模式"""
    token: str          # 原始文本 token
    category: str       # Entity / Relation / Attribute / Time / Question / Negation / Perspective
    confidence: float   # 分类置信度
    source: str = ""    # 来源: kg_known / position_guess / user_taught


# ═══════════════════════════════════════
#  语义假说 (Semantic Hypothesis)
# ═══════════════════════════════════════

@dataclass
class StructuralHypothesis:
    """一句话可能有多种结构解释——这是其中一种"""
    id: str
    text: str                      # 原始输入
    structure: dict                # {subject, predicate, object, question, negated, perspective}
    confidence: float = 0.5
    evidence: list[str] = field(default_factory=list)
    reasoning: str = ""

    def desc(self) -> str:
        s = self.structure
        return f"[{s.get('subject','?')}] --[{s.get('predicate','?')}]--> [{s.get('object','?')}]" + \
               (" ?" if s.get('question') else "") + \
               (" NOT" if s.get('negated') else "")


# ═══════════════════════════════════════
#  语用假说 (Pragmatic Hypothesis)
# ═══════════════════════════════════════

@dataclass
class PragmaticHypothesis:
    """用户在说这句话时，真正目的是什么？"""
    id: str
    type: str         # info_request / capability_check / social_ritual / test / complaint / teach
    label: str        # 人类可读标签
    confidence: float = 0.5
    reasoning: str = ""


# ═══════════════════════════════════════
#  关系假说 (Relation Hypothesis)
# ═══════════════════════════════════════

@dataclass
class RelationHypothesis:
    """一个关系词可能有多种解释 — 每个候选是一种假说"""
    word: str               # 原始关系词, 如 "绕" / "属于" / "会"
    candidate_type: str     # 候选关系类型: IS_A / ORBITS / CAUSES / CAN / DOES / RELATED
    confidence: float = 0.5
    evidence: list[str] = field(default_factory=list)
    reasoning: str = ""


class RelationHypothesisEngine:
    """
    关系假说引擎 — 不是 "属于=IS_A" 的死映射表。

    输入: 一个关系词 ("会")
    输出: 多个假说
      H1: CAN (0.7) — KG里"会 IS_A 助动词"
      H2: CAUSES (0.2) — 也可能是因果
      H3: RELATED (0.1) — 兜底
    """

    # 语言无关系类型枚举
    RELATION_TYPES = ["IS_A", "ORBITS", "CAUSES", "CAN", "DOES", "HAS", "LOCATED_AT", "RELATED"]

    def __init__(self, kg=None):
        self.kg = kg
        # 从 KG 学习的同义映射 (动态增长, 不硬编码)
        self.synonym_map: dict[str, dict[str, float]] = {}

    def hypothesize(self, word: str, context_entities: list[str] = None) -> list[RelationHypothesis]:
        """
        为一个关系词生成多个候选解释。

        优先级:
          1. KG 直接存储: 绕 IS_A 关系词 → 关系词映射
          2. KG 同义映射: 绕 SYNONYM_OF ORBITS → 直接映射
          3. 语法知识: 绕 MEANS 关系词 → 候选=ORBITS/RELATED
          4. 启发式降级
        """
        hyps = []

        # ── 路径1: KG 直接查询 ──
        if self.kg:
            for r in self.kg.relations:
                if r.subject != word:
                    continue
                obj = r.object.lower() if r.object else ""

                # 同义词直接映射
                if r.predicate == "IS_SYNONYM":
                    if obj.upper() in self.RELATION_TYPES:
                        hyps.append(RelationHypothesis(word, obj.upper(), 0.85,
                            [f"KG同义词: {word} SYNONYM_OF {obj}"],
                            f"直接同义映射: {word} → {obj}"))

                # 词性知识 → 推测关系类型
                if r.predicate in ("MEANS", "IS_A"):
                    types_from_kg = self._infer_from_word_type(obj)
                    for t, conf in types_from_kg:
                        hyps.append(RelationHypothesis(word, t, conf,
                            [f"KG词性: {word} {r.predicate} {r.object}"],
                            f"从词性推断: {obj} → {t}"))

        # ── 路径2: 结构启发式 ──
        heuristic = self._heuristic_guess(word, context_entities)
        if heuristic:
            hyps.extend(heuristic)

        # ── 兜底 ──
        if not hyps:
            hyps.append(RelationHypothesis(word, "RELATED", 0.3,
                [], "无法确定关系类型, 兜底"))

        return sorted(hyps, key=lambda h: h.confidence, reverse=True)

    def _infer_from_word_type(self, word_type: str) -> list[tuple[str, float]]:
        """从 KG 存储的词性描述推断关系类型"""
        results = []
        wt = word_type.lower()

        if any(k in wt for k in ("系动词", "copula", "linking")):
            results.append(("IS_A", 0.8))
        if any(k in wt for k in ("因果", "cause", "导致")):
            results.append(("CAUSES", 0.8))
        if any(k in wt for k in ("围绕", "orbit", "环绕")):
            results.append(("ORBITS", 0.8))
        if any(k in wt for k in ("助动词", "auxiliary", "能力", "ability")):
            results.append(("CAN", 0.7))
            results.append(("DOES", 0.4))  # 次级候选
        if any(k in wt for k in ("属于", "belong")):
            results.append(("IS_A", 0.75))
            results.append(("BELONGS_TO", 0.65)) if "belong" in wt else None
        if any(k in wt for k in ("位置", "located", "位于")):
            results.append(("LOCATED_AT", 0.8))
        if any(k in wt for k in ("关系", "relation")):
            results.append(("ORBITS", 0.5))
            results.append(("RELATED", 0.4))
        if any(k in wt for k in ("拥有", "has", "possess")):
            results.append(("HAS", 0.8))

        return results

    def _heuristic_guess(self, word: str, entities: list[str] = None) -> list[RelationHypothesis]:
        """降级启发式: 当 KG 没有词性信息时的位置/字符猜测"""
        hyps = []

        # 连词 (和/或) → 单个实体处理, 不是关系
        if word in ('和', '或', '与', 'and', 'or'):
            return []

        # 单字关系词常见映射
        if word in ('是', '为'):
            hyps.append(RelationHypothesis(word, "IS_A", 0.6, [], "常见系词"))
        elif word in ('绕',):
            hyps.append(RelationHypothesis(word, "ORBITS", 0.5, [], "常见轨道词"))
        elif word in ('会', '能', '可以'):
            hyps.append(RelationHypothesis(word, "CAN", 0.5, [], "常见助动词"))
            hyps.append(RelationHypothesis(word, "DOES", 0.3, [], "也可能是一般动作"))
        elif word in ('在', '于'):
            hyps.append(RelationHypothesis(word, "LOCATED_AT", 0.5, [], "常见位置词"))
        elif word in ('有',):
            hyps.append(RelationHypothesis(word, "HAS", 0.5, [], "常见拥有词"))
        else:
            hyps.append(RelationHypothesis(word, "RELATED", 0.3, [], "未知关系词"))

        return hyps


# ═══════════════════════════════════════
#  SemanticHypothesisEngine
# ═══════════════════════════════════════

class SemanticHypothesisEngine:
    """
    层一: "他说了什么?"

    v0.3: Entity Boundary Resolver + Relation Hypothesis Engine → 多候选组合。
    """

    def __init__(self, kg=None, db=None):
        self.kg = kg
        self.db = db
        self.patterns: list[dict] = []
        self.primitive_registry: dict[str, str] = {}
        self.relation_engine = RelationHypothesisEngine(kg)

    def hypothesize(self, text: str) -> list[StructuralHypothesis]:
        """
        生成结构假说——多实体+多关系候选组合。

        思考显性化: 每个假说附带 evidence 和 reasoning trace。
        """
        hypotheses = []
        primitives = self._extract_primitives(text)

        # 分类
        entities = [p for p in primitives if p.category == "Entity"]
        relation_words = [p for p in primitives if p.category == "Relation"]
        questions = [p for p in primitives if p.category == "Question"]
        negations = [p for p in primitives if p.category == "Negation"]
        perspectives = [p for p in primitives if p.category == "Perspective"]

        is_question = bool(questions)
        is_negated = bool(negations)

        if not entities and not relation_words:
            h = StructuralHypothesis("SH0", text,
                structure={"subject": None, "predicate": "UNPARSED", "object": None,
                           "question": is_question, "negated": is_negated, "perspective": "user"},
                confidence=0.1, reasoning="无法提取实体或关系")
            hypotheses.append(h)
            return hypotheses

        # ── 实体列表 ──
        entity_names = [e.token for e in entities]
        if len(entity_names) == 0:
            entity_names = [text]  # 整句当实体

        subject = entity_names[0]

        # ── 为每个关系词生成候选关系类型 ──
        all_relation_hyps = []
        for rw in relation_words:
            rhyps = self.relation_engine.hypothesize(rw.token, entity_names)
            all_relation_hyps.extend(rhyps)

        if not all_relation_hyps:
            # 无关系词 → 单实体
            h = StructuralHypothesis("SH1", text,
                structure={"subject": subject, "predicate": "IS_TOPIC", "object": None,
                           "question": is_question, "negated": is_negated,
                           "perspective": perspectives[0].token if perspectives else "user"},
                confidence=0.3,
                evidence=[f"entities={entity_names}"],
                reasoning="单实体, 无关系词")
            hypotheses.append(h)
            return sorted(hypotheses, key=lambda h: h.confidence, reverse=True)

        # ── 实体+关系组合: 为每个关系候选生成结构假说 ──
        obj = entity_names[1] if len(entity_names) > 1 else None

        for rh in all_relation_hyps[:5]:  # 最多 5 个候选
            h = StructuralHypothesis(
                f"SH_{rh.candidate_type}",
                text,
                structure={
                    "subject": subject,
                    "predicate": rh.candidate_type,
                    "object": obj,
                    "question": is_question,
                    "negated": is_negated,
                    "perspective": perspectives[0].token if perspectives else "user",
                },
                confidence=rh.confidence,
                evidence=[f"entity={subject}", f"relation_word={rh.word}",
                          f"relation_candidate={rh.candidate_type}"] + rh.evidence,
                reasoning=rh.reasoning
            )

            # ── KG 验证: 如果实体和关系在 KG 中存在，加权 ──
            if self.kg and obj:
                kg_boost = self._validate_against_kg(subject, rh.candidate_type, obj)
                h.confidence = min(0.95, h.confidence + kg_boost)
                if kg_boost > 0.05:
                    h.evidence.append(f"KG验证: +{kg_boost:.2f}")

            hypotheses.append(h)

        return sorted(hypotheses, key=lambda h: h.confidence, reverse=True)

    def _validate_against_kg(self, subject: str, predicate: str, obj: str) -> float:
        """KG 验证: 查找是否有支持证据"""
        if not self.kg:
            return 0.0
        boost = 0.0
        # 精确匹配
        for r in self.kg.relations:
            if r.subject == subject and r.predicate == predicate and r.object == obj:
                boost += 0.15
            # 传递推理: subject IS_A something, something IS_A obj
            if predicate == "IS_A":
                for r2 in self.kg.relations:
                    if r.subject == subject and r.predicate == "IS_A" and r.object == r2.subject and r2.predicate == "IS_A" and r2.object == obj:
                        boost += 0.1
        return boost

    def _resolve_entity_boundaries(self, text: str) -> list[str]:
        """
        KG 驱动的实体边界解析器 v0.2。

        - 中文: KG 最长匹配优先，未匹配单字合并，遇已知功能词/关系词停止合并
        - 英文/数字: 连续 ASCII 或数字保持为一词
        """
        if not self.kg:
            return re.findall(r'[\u4e00-\u9fff]+|[a-zA-Z]+|\d+', text)

        known_entities: dict[str, int] = {}
        for r in self.kg.relations:
            for candidate in (r.subject, r.object):
                if candidate and len(candidate) >= 2:
                    known_entities[candidate] = len(candidate)

        known_func_words = set()
        for w in ('是','绕','围绕','属于','会','能','吗','呢','吧',
                  '不','是否','什么','谁','哪','怎么','如何','不是',
                  '导致','引起','和','或','但','而','也','都','还',
                  '了','着','过','的','在','被','把','让','用','对',
                  'is','can','orbits','causes','belongs','includes','the','a','an'):
            known_func_words.add(w)

        sorted_entities = sorted(known_entities.keys(), key=lambda x: -len(x))

        tokens = []
        i = 0
        while i < len(text):
            # 英文/数字: 连续 ASCII 或数字
            if text[i].isascii() and text[i].isalpha():
                j = i
                while j < len(text) and text[j].isascii() and (text[j].isalpha() or text[j] == ' '):
                    j += 1
                word = text[i:j].strip()
                if word:
                    for subword in word.split():
                        tokens.append(subword)
                i = j
                continue

            # 中文: KG 最长匹配
            matched = False
            for entity in sorted_entities:
                if text[i:].startswith(entity):
                    tokens.append(entity)
                    i += len(entity)
                    matched = True
                    break
            if not matched:
                tokens.append(text[i])
                i += 1

        # 合并相邻单中文字: "地"+"球" → "地球", 遇功能词则断开
        merged = []
        buffer = ""
        for tok in tokens:
            is_single_cn = len(tok) == 1 and '\u4e00' <= tok <= '\u9fff'
            if is_single_cn:
                # 功能词或已知关系词 → 断开
                if tok in known_func_words or tok in self.primitive_registry:
                    if buffer:
                        merged.append(buffer)
                        buffer = ""
                    merged.append(tok)
                else:
                    buffer += tok
            else:
                if buffer:
                    merged.append(buffer)
                    buffer = ""
                merged.append(tok)
        if buffer:
            merged.append(buffer)

        return merged

    def _extract_primitives(self, text: str) -> list[LanguagePrimitive]:
        """
        从文本中提取语言原语。

        v0.2: 用 KG 已知实体边界 → 最长匹配优先 → 不切碎多字实体。
        """
        prims = []
        tokens = self._resolve_entity_boundaries(text)

        for i, tok in enumerate(tokens):
            cat = self._classify_token(tok, i, tokens)
            conf = 0.7 if tok in self.primitive_registry else 0.5
            prims.append(LanguagePrimitive(tok, cat, conf,
                         "kg" if tok in self.primitive_registry else "heuristic"))

        return prims

    def _classify_token(self, token: str, position: int, all_tokens: list) -> str:
        """
        分类一个 token 的语言原语类型。

        优先查 KG, 其次用位置启发。
        """
        # KG 已有知识?
        if self.kg:
            for r in self.kg.relations:
                if r.subject == token:
                    obj = r.object.lower() if r.object else ""
                    if "系动词" in obj or "copula" in obj or "relation" in obj or "关系" in obj:
                        self.primitive_registry[token] = "Relation"
                        return "Relation"
                    if "疑问" in obj or "question" in obj:
                        self.primitive_registry[token] = "Question"
                        return "Question"
                    if "否定" in obj or "negation" in obj:
                        self.primitive_registry[token] = "Negation"
                        return "Negation"
                    if "助词" in obj or "量词" in obj or "冠词" in obj or "article" in obj:
                        self.primitive_registry[token] = "Attribute"
                        return "Attribute"
                    if "时间" in obj or "time" in obj:
                        self.primitive_registry[token] = "Time"
                        return "Time"
                    if "助动词" in obj or "auxiliary" in obj or "能力" in obj:
                        self.primitive_registry[token] = "Relation"
                        return "Relation"
                    if "因果" in obj or "导致" in obj or "cause" in obj:
                        self.primitive_registry[token] = "Relation"
                        return "Relation"
                    if "连词" in obj or "conjunction" in obj:
                        self.primitive_registry[token] = "Attribute"
                        return "Attribute"

        # 位置启发式 (KG 没教语法词时的降级)
        if token in ('吗', '呢', '吧', '?', '？', '什么', '谁', '哪', '怎么', '如何', '是否'):
            self.primitive_registry[token] = "Question"
            return "Question"
        if token in ('不', '没', '别', '无', '非', '不是'):
            self.primitive_registry[token] = "Negation"
            return "Negation"
        if token in ('是', '绕', '围绕', '属于', '导致', '引起', '和', '或'):
            self.primitive_registry[token] = "Relation"
            return "Relation"
        if token in ('会', '能', '可以'):
            self.primitive_registry[token] = "Relation"  # 助动词 = 关系子类
            return "Relation"
            self.primitive_registry[token] = "Question"
            return "Question"
        if token in ('不', '没', '别', '无', '非'):
            self.primitive_registry[token] = "Negation"
            return "Negation"
        if token in ('你', '我', '他', '她', '它', '我们', '你们', '他们', '谁', '大家'):
            self.primitive_registry[token] = "Perspective"
            return "Perspective"
        if position == 0:
            return "Entity"
        if re.match(r'^\d+$', token):
            return "Attribute"

        # 未知 → 默认 Entity
        return "Entity"

    def _guess_relation_type(self, relation: str) -> str:
        """根据 KG 知识推测关系类型"""
        if self.kg:
            for r in self.kg.relations:
                if r.subject == relation and r.predicate in ("IS_A", "MEANS"):
                    obj = r.object.lower() if r.object else ""
                    if "is_a" in obj or "系动词" in obj or "copula" in obj:
                        return "IS_A"
                    if "cause" in obj or "导致" in obj or "因果" in obj:
                        return "CAUSES"
                    if "orbit" in obj or "围绕" in obj or "关系词" in obj:
                        return "ORBITS"
                    if "belong" in obj or "属于" in obj:
                        return "BELONGS_TO"
                    if "can" in obj or "ability" in obj or "能力" in obj or "助动词" in obj:
                        return "CAN"
                    if "action" in obj:
                        return "DOES"
        # 降级: 硬编码常见关系词
        if relation in ('绕', '围绕'): return "ORBITS"
        if relation in ('导致', '引起', '产生', '造成'): return "CAUSES"
        if relation in ('属于', '是'): return "IS_A"
        if relation in ('会', '能', '可以'): return "CAN"
        return "IS_A"

    def register_pattern(self, pattern: dict, confidence: float):
        """从成功的交互中注册语言模式"""
        self.patterns.append({**pattern, "confidence": confidence, "count": 1})


# ═══════════════════════════════════════
#  PragmaticIntentEngine
# ═══════════════════════════════════════

class PragmaticIntentEngine:
    """
    层二: "为什么说?"

    v2: 零关键词匹配。意图只从句子结构推断。
    用户说"你好"但没教过"问候语"概念 → AM 不知道该做什么 → 诚实说不知道。
    """

    def __init__(self, kg=None):
        self.kg = kg

    def hypothesize(self, structural, context=None):
        struct = structural.structure
        hyps = []

        # H1: 信息询问 — 含疑问标记 + 已知关系
        if struct.get("question") and struct.get("predicate") in (
            "IS_A", "CAN", "DOES", "ORBITS", "CAUSES", "HAS", "LOCATED_AT"):
            hyps.append(PragmaticHypothesis("PH1", "info_request",
                f"用户想知道: {struct.get('subject')} {struct.get('predicate')} {struct.get('object')}?",
                0.75, "三元组+疑问标记"))

        # H2: 自我指涉 — 视角=你 + 疑问
        if struct.get("perspective") == "你" and struct.get("question"):
            hyps.append(PragmaticHypothesis("PH2", "self_directed",
                "用户在问关于 AM 自身的问题", 0.65, "视角=你+疑问"))

        # H3: 低置信——无法确定, 诚实承认
        if not hyps:
            hyps.append(PragmaticHypothesis("PH3", "uncertain",
                f"无法从结构确定意图 (置信度{structural.confidence:.0%})",
                0.3, "无匹配结构模式"))

        return sorted(hyps, key=lambda h: h.confidence, reverse=True)


class ActionIntentEngine:
    """
    层三: "执行什么动作?"

    这是旧 IntentLayer 中的命令路由部分——保留, 但移到最后。

    只在 Semantic + Pragmatic 无法确定时作为兜底。
    """

    COMMANDS = {
        'learnw': ('learn_word', 0.9),
        'readcn': ('read_chinese', 0.9),
        'answer': ('user_teach', 0.9),
        '以后我': ('set_preference', 0.9),
    }

    def detect(self, text: str) -> Optional[dict]:
        """检测是否是明确的命令操作"""
        for prefix, (action, conf) in self.COMMANDS.items():
            if text.startswith(prefix):
                return {"action": action, "confidence": conf, "command": text}
        return None


# ═══════════════════════════════════════
#  Cognitive Interface (总入口)
# ═══════════════════════════════════════

class CognitiveInterface:
    """
    AM 的感官层——不是路由表, 是三个引擎的管道。

    输入 → Semantic → Pragmatic → Action → Cognitive Core
    """

    def __init__(self, kg=None, db=None):
        self.kg = kg
        self.db = db
        self.semantic = SemanticHypothesisEngine(kg, db)
        self.pragmatic = PragmaticIntentEngine(kg)
        self.action = ActionIntentEngine()

        # 注册: 已学到的语言原语
        self._load_kg_primitives()

    def _load_kg_primitives(self):
        """从 KG 加载已知的语言原语词性"""
        if not self.kg: return
        for r in self.kg.relations:
            if r.predicate in ("IS_A", "MEANS"):
                obj = r.object.lower() if r.object else ""
                if "系动词" in obj or "copula" in obj:
                    self.semantic.primitive_registry[r.subject] = "Relation"
                elif "疑问" in obj or "question" in obj:
                    self.semantic.primitive_registry[r.subject] = "Question"
                elif "否定" in obj or "negation" in obj:
                    self.semantic.primitive_registry[r.subject] = "Negation"
                elif "时间" in obj or "time" in obj:
                    self.semantic.primitive_registry[r.subject] = "Time"
                elif "助词" in obj or "量词" in obj or "冠词" in obj or "article" in obj:
                    self.semantic.primitive_registry[r.subject] = "Attribute"

    def process(self, text: str, context: dict = None) -> dict:
        """
        完整认知接口管道。

        返回:
          { action, reply, reasoning, semantic, pragmatic, explanation }
        """
        result = {
            "action": "unknown",
            "reply": "",
            "reasoning": [],
            "semantic": None,
            "pragmatic": None,
            "explanation": [],
        }

        # ── 层一: Semantic — "他说了什么?" ──
        struct_hyps = self.semantic.hypothesize(text)
        best_struct = struct_hyps[0] if struct_hyps else None
        result["semantic"] = best_struct
        result["semantic_candidates"] = [h.desc() for h in struct_hyps[:3]]
        if best_struct:
            result["reasoning"].append(f"结构:{best_struct.desc()} ({best_struct.confidence:.0%})")
            # 思考显性化
            for ev in best_struct.evidence:
                result["explanation"].append(f"  · {ev}")
            result["explanation"].append(f"  ⇒ {best_struct.reasoning}")

        # ── 层二: Pragmatic — "为什么说?" ──
        if best_struct:
            # 事实学习检测: 有主语+关系+宾语, 不是问句 → 学习!
            struct = best_struct.structure
            is_statement = (struct.get("subject") and struct.get("predicate")
                            and struct.get("object")
                            and struct.get("predicate") in ("IS_A","CAN","CAUSES","ORBITS","DOES")
                            and not struct.get("question"))
            if is_statement:
                result["action"] = "fact_learn"
                result["pragmatic"] = None
                return result

            prag_hyps = self.pragmatic.hypothesize(best_struct, context)
            best_prag = prag_hyps[0] if prag_hyps else None
            result["pragmatic"] = best_prag
            if best_prag:
                result["reasoning"].append(f"意图:{best_prag.label} ({best_prag.confidence:.0%})")
                result["action"] = best_prag.type

        # ── 层三: Action — 命令路由 (兜底) ──
        cmd = self.action.detect(text)
        if cmd:
            result["action"] = cmd["action"]

        # ── 构建解释链 ──
        result["explanation"] = result["reasoning"].copy()

        return result

    def generate_reply(self, result: dict, text: str = "") -> str:
        """根据语义+语用+认知结果, 生成回复——零模板兜底"""
        action = result.get("action", "")
        sem = result.get("semantic")
        prag = result.get("pragmatic")

        # 事实学习——存 KG
        if action == "fact_learn" and sem:
            s = sem.structure
            subj, pred, obj = s.get("subject"), s.get("predicate"), s.get("object")
            if subj and pred and obj and self.kg and self.db:
                self.kg.add(subj, pred, obj, confidence=0.7)
                self.db.add_relation(subj, pred, obj, 0.7, source="web")
            return f"✅ 学会了: {subj} {pred} {obj}"

        if prag:
            if prag.type == "info_request":
                if sem:
                    s = sem.structure
                    subj = s.get("subject")
                    kg_hits = []
                    if self.kg and subj:
                        for r in self.kg.relations:
                            if r.subject == subj and r.confidence > 0.5:
                                kg_hits.append(r)
                    if kg_hits:
                        lines = [f"  · {r.subject} --[{r.predicate}]--> {r.object}" for r in kg_hits[:5]]
                        return "我找到这些:\n" + "\n".join(lines)
                    return f"关于 {subj} 我还不知道。你能教我吗?"

            if prag.type == "self_directed":
                facts = self.db.count() if self.db else 0
                return f"我是 AsteriaMind, 存储了 {facts} 条知识。你想让我学什么?"

            if prag.type == "uncertain":
                return f"我不太确定你的意思 😅 能换个方式说吗? 比如 'X是Y' 或 'X会Y吗'?"

        return "我听到了。但不太确定怎么回应——试试教我点什么?"


    