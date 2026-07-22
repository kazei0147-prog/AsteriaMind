"""
SkillLibrary — AM 的可组合能力目录 (AsteriaMind v3.2)

不是脚本列表。是 AM 知道自己会什么、什么时候该用哪个的元能力层。

每个 Skill:
  - 有元数据: 做什么、什么时候用、输入输出
  - 可被 QueryRouter 查找: "哪个 Skill 能处理数值查询?"
  - 可被 MH 反思: "我是不是缺某种 Skill?"
  - 可动态注册: 新能力自然加入目录
"""
import time
from dataclasses import dataclass, field
from typing import Callable, Optional, List, Dict, Any


@dataclass
class Skill:
    """AM 的一个可调用能力"""
    id: str                        # "math_solve"
    name: str                      # "数学求解"
    description: str               # "数值计算、求导、积分、模式识别"
    category: str                  # "math" | "search" | "analysis" | "cognitive" | "io"

    # 何时使用
    triggers: List[str]            # ["数字", "运算", "求导", "积分"]
    query_patterns: List[str]      # 正则片段: ["\\\\d+[+\\\\-*/]\\\\d+"]

    # 使用后效果
    produces: str                  # "计算结果以 math_derived 来源进入 KG"

    # 实际调用
    handler: Optional[Callable] = None  # (query: str, kg) → result: dict

    # 统计
    times_used: int = 0
    times_successful: int = 0
    created_at: float = field(default_factory=time.time)

    def execute(self, query: str, kg=None) -> dict:
        """执行此 Skill"""
        if self.handler:
            self.times_used += 1
            result = self.handler(query, kg)
            if result and result.get("success"):
                self.times_successful += 1
            return result or {"success": False, "error": "no result"}
        return {"success": False, "error": "no handler"}


class SkillLibrary:
    """
    AM 的能力目录——她知道自己在哪些方面有工具可用。

    用法:
      lib = SkillLibrary()
      lib.register(skill)
      match = lib.match("2+3=?" )  → [math_solve]
      result = match[0].execute("2+3=?", kg)
    """

    def __init__(self):
        self.skills: Dict[str, Skill] = {}
        self.usage_log: List[dict] = []

    def register(self, skill: Skill):
        self.skills[skill.id] = skill

    def match(self, query: str, category: str = None) -> List[Skill]:
        """
        根据查询特征匹配最合适的 Skill。

        匹配规则:
          1. 精确关键词触发
          2. 正则模式匹配
          3. 默认: 通过 category 筛选
        """
        import re
        candidates = []

        for skill in self.skills.values():
            if category and skill.category != category:
                continue

            # 精确关键词
            if any(t in query for t in skill.triggers):
                candidates.append((skill, 1.0))
                continue

            # 正则匹配
            for pat in skill.query_patterns:
                if re.search(pat, query):
                    candidates.append((skill, 0.8))
                    break

        if not candidates and category:
            # 默认返回该 category 的所有 skill
            candidates = [(s, 0.3) for s in self.skills.values() if s.category == category]

        candidates.sort(key=lambda x: -x[1])
        return [c[0] for c in candidates]

    def best_match(self, query: str) -> Optional[Skill]:
        """最匹配的 Skill"""
        matches = self.match(query)
        return matches[0] if matches else None

    def list_by_category(self) -> Dict[str, List[str]]:
        """按类别列出所有 Skill"""
        result: Dict[str, List[str]] = {}
        for skill in self.skills.values():
            result.setdefault(skill.category, []).append(f"{skill.id}: {skill.description}")
        return result

    def get_missing_triggers(self, query: str) -> str:
        """
        当没有 Skill 匹配时，报告原因。
        MH 可以用这个来发现"我缺少某类工具"。
        """
        if not self.skills:
            return "没有注册任何 Skill"
        # 分析哪些 trigger 可能覆盖了这个查询
        query_lower = query.lower()
        all_triggers = set()
        for s in self.skills.values():
            all_triggers.update(t.lower() for t in s.triggers)
        # 检查查询中是否有数字 (暗示需要 math skill)
        import re
        if re.search(r'\d', query) and "math" not in str([s.category for s in self.skills.values()]):
            return "查询包含数值但缺少数学 Skill"
        return f"查询'{query[:30]}...'未匹配任何现有 Skill 触发词"


def build_default_skills() -> SkillLibrary:
    """构建 AM 的默认 Skill Library"""
    lib = SkillLibrary()

    # ── math 类别 ──
    def math_handler(query, kg=None):
        from AsteriaMind.math_reasoner import MathReasoner
        mr = MathReasoner()
        result = mr.solve(query, kg=kg)
        if result:
            if kg:
                kg.add(query.strip(), "EQUALS", str(result.result),
                       confidence=result.confidence, source="math_derived")
            return {"success": True, "result": result.result, "steps": result.steps}
        return {"success": False, "error": "无法解析数学表达式"}

    lib.register(Skill(
        id="math_solve", name="数学求解", category="math",
        description="四则运算、代数、微积分、模式识别、单位转换",
        triggers=["+", "-", "*", "/", "^", "=", "sqrt", "导数", "积分", "极限",
                  "derivative", "integral", "limit", "x=", "求导", "模式", "mile", "km"],
        query_patterns=[r'\d+[\+\-\*/\^]\d+', r'x\s*[\+\-\*/]\s*\d+\s*=\s*\d+'],
        produces="计算结果以 math_derived 进入 KG",
        handler=math_handler,
    ))

    # ── search 类别 ──
    def search_handler(query, kg=None):
        from AsteriaMind.falsification import WebSearchInterface
        ws = WebSearchInterface()
        results = ws.search(query, max_results=3)
        return {"success": True, "results": [
            {"title": r.title, "snippet": r.snippet[:200]} for r in results
        ]}

    lib.register(Skill(
        id="web_search", name="网络搜索", category="search",
        description="联网搜索外部信息",
        triggers=["搜索", "查一下", "search", "什么是", "最近"],
        query_patterns=[],
        produces="搜索结果返回给调用方",
        handler=search_handler,
    ))

    # ── analysis 类别 ──
    def audit_handler(query, kg=None):
        if not kg:
            return {"success": False, "error": "需要 KG"}
        from AsteriaMind.certainty_audit import CertaintyAudit
        ca = CertaintyAudit()
        findings = ca.audit(kg)
        return {"success": True, "findings": [
            {"key": f.relation_key, "risk": f.risk_level, "reasons": f.reasons}
            for f in findings[:5]
        ]}

    lib.register(Skill(
        id="certainty_audit", name="信念审计", category="analysis",
        description="压力测试高置信度信念，发现结构性盲区",
        triggers=["审计", "检查", "audit", "压力测试", "盲区"],
        query_patterns=[],
        produces="审计报告",
        handler=audit_handler,
    ))

    # ── cognitive 类别 ──
    def analog_handler(query, kg=None):
        return {"success": True, "query": query, "note": "语义类比接口已就绪"}

    lib.register(Skill(
        id="semantic_analogy", name="语义类比", category="cognitive",
        description="在向量空间中寻找与查询最接近的知识",
        triggers=["类比", "像", "类似", "analogy", "assoc"],
        query_patterns=[],
        produces="语义相似知识列表",
        handler=analog_handler,
    ))

    return lib
