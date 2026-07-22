"""
MathReasoner — AM 的数学推理模块 (AsteriaMind v3.2)

不是传统符号数学引擎。
是 AM 认知体系中的数学工具: 计算结果以 "derived" 来源进入 KG,
经过 α/β 验证, 可被反证挑战, 可参与假说竞争。

支持: 四则运算 / 简单代数 / 模式识别 / 单位转换
"""
import re
import math
from dataclasses import dataclass
from typing import Optional, Tuple


@dataclass
class MathResult:
    """一次数学推理的结果"""
    expression: str
    result: float
    steps: list[str]
    confidence: float     # 计算结果的可信度 (计算本身是确定的, 但解析可能出错)
    source: str = "math_derived"


class MathReasoner:
    """
    AM 的数学推理引擎。

    计算结果以 derived 来源进入 KG:
      confidence = 0.95 (计算是确定的)
      source = "math_derived"
      → 可被反证挑战 (比如用户说"算错了")
    """

    def solve(self, query: str) -> Optional[MathResult]:
        """解析并求解数学问题。返回 None 如果无法处理。"""
        q = query.strip()

        # 微积分
        result = self._derivative(q)
        if result is not None:
            return result
        result = self._integral(q)
        if result is not None:
            return result
        result = self._limit(q)
        if result is not None:
            return result

        # 四则运算
        result = self._arithmetic(q)
        if result is not None:
            return result

        # 简单代数: "x + 5 = 10"
        result = self._algebra(q)
        if result is not None:
            return result

        # 模式识别: "2, 4, 6, 8, ?"
        result = self._pattern(q)
        if result is not None:
            return result

        # 单位转换: "1 mile = ? km"
        result = self._convert(q)
        if result is not None:
            return result

        # 乘方/开方
        result = self._sqrt(q)
        if result is not None:
            return result
        result = self._power(q)
        if result is not None:
            return result

        return None

    def _arithmetic(self, q: str) -> Optional[MathResult]:
        """四则运算: 2 + 3 * 4, (5 - 2) / 3 等"""
        # 只保留数字和运算符
        cleaned = re.sub(r'[^0-9+\-*/().^%\s]', '', q)
        if not cleaned or not re.search(r'[+\-*/]', cleaned):
            return None
        try:
            cleaned = cleaned.replace('^', '**')
            result = eval(cleaned, {"__builtins__": {}},
                         {"math": math, "sqrt": math.sqrt, "pi": math.pi,
                          "sin": math.sin, "cos": math.cos, "tan": math.tan,
                          "log": math.log, "log10": math.log10, "exp": math.exp,
                          "abs": abs, "pow": pow})
            return MathResult(
                expression=q,
                result=result,
                steps=[f"计算: {cleaned} = {result}"],
                confidence=0.95,
            )
        except Exception:
            return None

    def _algebra(self, q: str) -> Optional[MathResult]:
        """简单代数: x + 5 = 10, 2x = 8, x/2 = 5"""
        # 匹配: (数字)*(x) (+-*/) (数字) = (数字)
        m = re.search(r'([\d.]*)\s*\*?\s*x\s*([+\-*/])\s*([\d.]+)\s*=\s*([\d.]+)', q)
        if m:
            coeff = float(m.group(1)) if m.group(1) else 1.0
            op = m.group(2)
            b = float(m.group(3))
            c = float(m.group(4))

            if op == '+':
                x = (c - b) / coeff
            elif op == '-':
                x = (c + b) / coeff
            elif op == '*':
                x = c / (coeff * b) if b != 0 else None
            elif op == '/':
                x = c * b / coeff
            else:
                return None

            if x is not None:
                return MathResult(
                    expression=q,
                    result=x,
                    steps=[f"解: x = {x}"],
                    confidence=0.95,
                )

        # 匹配: x = 数字
        m = re.search(r'x\s*=\s*([\d.]+)', q)
        if m:
            return MathResult(
                expression=q,
                result=float(m.group(1)),
                steps=[f"x = {m.group(1)}"],
                confidence=0.95,
            )

        return None

    def _pattern(self, q: str) -> Optional[MathResult]:
        """模式识别: 2, 4, 6, 8, ?"""
        m = re.search(r'([\d\s,.]+)\s*\?', q)
        if not m:
            return None

        nums_str = m.group(1).strip()
        nums = [float(n) for n in re.findall(r'[\d.]+', nums_str)]
        if len(nums) < 3:
            return None

        # 检测等差数列
        diffs = [nums[i+1] - nums[i] for i in range(len(nums)-1)]
        if max(diffs) - min(diffs) < 0.001:
            next_val = nums[-1] + diffs[0]
            return MathResult(
                expression=q,
                result=next_val,
                steps=[f"等差数列, 公差={diffs[0]:.1f}, 下一个={next_val}"],
                confidence=0.9,
            )

        # 检测等比数列
        if all(d != 0 for d in nums):
            ratios = [nums[i+1] / nums[i] for i in range(len(nums)-1)]
            if max(ratios) - min(ratios) < 0.001:
                next_val = nums[-1] * ratios[0]
                return MathResult(
                    expression=q,
                    result=next_val,
                    steps=[f"等比数列, 公比={ratios[0]:.2f}, 下一个={next_val}"],
                    confidence=0.85,
                )

        return None

    def _convert(self, q: str) -> Optional[MathResult]:
        """单位转换"""
        conversions = {
            ("mile", "km"): 1.60934,
            ("km", "mile"): 0.621371,
            ("inch", "cm"): 2.54,
            ("cm", "inch"): 0.393701,
            ("foot", "meter"): 0.3048,
            ("meter", "foot"): 3.28084,
            ("pound", "kg"): 0.453592,
            ("kg", "pound"): 2.20462,
            ("celsius", "fahrenheit"): "lambda c: c * 9/5 + 32",
            ("fahrenheit", "celsius"): "lambda f: (f - 32) * 5/9",
            ("hour", "minute"): 60,
            ("minute", "second"): 60,
            ("day", "hour"): 24,
        }

        m = re.search(r'([\d.]+)\s*(\w+)\s*(?:[=＝to到→]|\s)\s*\??\s*(\w+)', q, re.IGNORECASE)
        if not m:
            return None

        value = float(m.group(1))
        from_unit = m.group(2).lower()
        to_unit = m.group(3).lower() if m.group(3) else ""

        # 尝试匹配
        for (f, t), factor in conversions.items():
            if f in from_unit:
                if not to_unit or t in to_unit:
                    if isinstance(factor, str):
                        # lambda 字符串 → eval
                        result = eval(factor)(value)
                    else:
                        result = value * factor
                    return MathResult(
                        expression=q,
                        result=result,
                        steps=[f"{value} {from_unit} = {result:.4f} {t}"],
                        confidence=0.95,
                    )

        return None

    def _sqrt(self, q: str) -> Optional[MathResult]:
        """开方: sqrt 16, sqrt(25)"""
        m = re.search(r'sqrt\s*\(?\s*([\d.]+)\s*\)?', q)
        if m:
            val = float(m.group(1))
            result = math.sqrt(val)
            return MathResult(
                expression=q,
                result=result,
                steps=[f"sqrt({val}) = {result}"],
                confidence=0.95,
            )
        return None

    def _power(self, q: str) -> Optional[MathResult]:
        """乘方: 2^10"""
        m = re.search(r'([\d.]+)\s*\^?\s*(\d+)', q)
        if m:
            base = float(m.group(1))
            exp = int(m.group(2))
            result = base ** exp
            return MathResult(
                expression=q,
                result=result,
                steps=[f"{base}^{exp} = {result}"],
                confidence=0.95,
            )
        return None

    # ── 微积分 ──

    def _derivative(self, q: str) -> Optional[MathResult]:
        """求导: derivative x^2 at x=3, d/dx x^3"""
        m = re.search(r"(?:derivative|求导|导数)\s*(?:of\s*)?(.+?)\s*(?:at|在)\s*x\s*=\s*([\d.]+)", q, re.IGNORECASE)
        if m:
            expr = m.group(1).strip()
            x0 = float(m.group(2))
            return self._numerical_derivative(q, expr, x0)

        m = re.search(r"d/dx\s+(.+)", q)
        if m:
            return self._symbolic_derivative(q, m.group(1).strip())

        m = re.search(r"f\(x\)\s*=\s*(.+?)[,;]\s*f'?\(?([\d.]+)\)?", q)
        if m:
            return self._numerical_derivative(q, m.group(1).strip(), float(m.group(2)))
        return None

    def _integral(self, q: str) -> Optional[MathResult]:
        """定积分: integral x^2 from 0 to 1"""
        m = re.search(r"(?:integral|积分|∫)\s*(.+?)\s*(?:from|_)\s*([\d.]+)\s*(?:to|_)\s*([\d.]+)", q, re.IGNORECASE)
        if m:
            return self._numerical_integral(q, m.group(1).strip(), float(m.group(2)), float(m.group(3)))
        return None

    def _limit(self, q: str) -> Optional[MathResult]:
        """极限: limit sin(x)/x as x→0"""
        m = re.search(r"(?:limit|极限)\s*(.+?)\s*(?:as|当)\s*x\s*→\s*([\d.]+)", q, re.IGNORECASE)
        if m:
            return self._numerical_limit(q, m.group(1).strip(), float(m.group(2)))
        return None

    def _numerical_derivative(self, query: str, expr: str, x0: float) -> MathResult:
        h = 0.0001
        def f(x):
            return self._eval_expr(expr.replace("x", f"({x})"))
        fxh = f(x0 + h)
        fxh_m = f(x0 - h)
        deriv = (fxh - fxh_m) / (2 * h)
        return MathResult(expression=query, result=round(deriv, 6),
                          steps=[f"f'({x0}) ≈ ({fxh:.6f} - {fxh_m:.6f}) / {2*h} = {deriv:.6f}"],
                          confidence=0.9)

    def _symbolic_derivative(self, query: str, expr: str) -> Optional[MathResult]:
        expr = expr.strip()
        m = re.match(r'([\d.]*)\s*\*?\s*x\^?(\d+)', expr)
        if m:
            a = float(m.group(1)) if m.group(1) else 1.0
            n = float(m.group(2))
            r = f"{a*n}x" + (f"^{int(n-1)}" if n > 2 else "")
            return MathResult(expression=query, result=float(a*n),
                              steps=[f"d/dx({expr}) = {r}"], confidence=0.95)
        specials = {"sin(x)": "cos(x)", "cos(x)": "-sin(x)", "e^x": "e^x", "ln(x)": "1/x"}
        if expr in specials:
            return MathResult(expression=query, result=0.0,
                              steps=[f"d/dx({expr}) = {specials[expr]}"], confidence=0.95)
        return None

    def _numerical_integral(self, query: str, expr: str, a: float, b: float) -> MathResult:
        n = 1000
        h = (b - a) / n
        def f(x):
            return self._eval_expr(expr.replace("x", f"({x})"))
        s = f(a) + f(b)
        for i in range(1, n, 2):
            s += 4 * f(a + i * h)
        for i in range(2, n - 1, 2):
            s += 2 * f(a + i * h)
        result = s * h / 3
        return MathResult(expression=query, result=round(result, 6),
                          steps=[f"∫[{a},{b}] {expr} dx = {result:.6f} (Simpson n={n})"],
                          confidence=0.9)

    def _numerical_limit(self, query: str, expr: str, target: float) -> MathResult:
        def f(x):
            return self._eval_expr(expr.replace("x", f"({x})"))
        steps = []
        prev = None
        for h in [0.1, 0.01, 0.001, 0.0001]:
            val = f(target + h)
            steps.append(f"h={h}: f({target+h:.4f}) = {val:.8f}")
            prev = val
        return MathResult(expression=query, result=round(f(target + 0.00001), 6),
                          steps=[f"lim(x→{target}) {expr}:"] + steps,
                          confidence=0.85)

    def _eval_expr(self, expr: str) -> float:
        try:
            return eval(expr.replace('^', '**'), {"__builtins__": {}},
                       {"math": math, "sqrt": math.sqrt, "pi": math.pi,
                        "sin": math.sin, "cos": math.cos, "tan": math.tan,
                        "log": math.log, "exp": math.exp, "abs": abs, "e": math.e})
        except Exception:
            return 0.0
