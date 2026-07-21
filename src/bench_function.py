"""
v2.8 FunctionLearner 验证: 学习 y=2x+5 + 结构断层检测

双入口: FunctionLearner 学结构 + ResidualLearner 学噪声
"""
import sys, random
sys.path.insert(0, "D:/AM/HiveMind_repo/src")

from AsteriaMind.function_learner import FunctionLearner
from AsteriaMind.learner import Learner
from AsteriaMind.trust import TrustEngine
from AsteriaMind.mother import MotherMind
from AsteriaMind.portal import Portal, LiveSource, ConsoleSink, CuriosityEngine

random.seed(42)

fl = FunctionLearner(dim=2, forgetting=0.99)
live = LiveSource(max_buffer=200)

# ── 入口1: FunctionLearner 学结构 ──
# ── 入口2: ResidualLearner 学噪声 ──
learners = [
    Learner(name="L1", initial_mu=0, initial_sigma=5, window_size=5,
            adaptive_scale=True, robust_likelihood=True),
    Learner(name="L2", initial_mu=0, initial_sigma=10, window_size=10,
            adaptive_scale=True, robust_likelihood=True),
]
trust = TrustEngine()
for l in learners:
    trust.register(l.learner_id)
mother = MotherMind()

portal = Portal(source=live, sinks=[ConsoleSink()],
    curiosity=CuriosityEngine(confidence_low=0.7, knowledge_gap_rounds=3))

# ── 阶段1: y=2x+5 + noise (500轮) ──
print("=" * 60)
print("📐 v2.8 FunctionLearner: 学习 y=2x+5")
print("=" * 60)

errors_fl = []
errors_res = []

for x in range(500):
    y_true = 2 * x + 5
    y_obs = y_true + random.gauss(0, 3)
    live.push(y_obs)

    # 入口1: FunctionLearner
    fl.update(x, y_obs)
    y_base = fl.predict(x)
    error_fl = abs(y_base - y_true)
    errors_fl.append(error_fl)

    # 入口2: ResidualLearner
    residual = y_obs - y_base  # 应该是纯噪声 ~N(0,3)
    for l in learners:
        l.observe(residual)  # 观察残差而非原始值
        if l.observation_window:
            prop = l.propose(residual).proposal_value
            if x % 5 == 0:  # 偶尔讨论
                chains = [ll.propose(residual) for ll in learners
                          if ll.observation_window]
                if chains:
                    mother.deliberate(learners, chains, trust, residual)

# ── 结果 ──
print(f"\nFunctionLearner 500轮后:")
s = fl.summary()
print(f"  学习到: y = {s['a']:.4f}x + {s['b']:.4f}")
print(f"  目标:   y = 2.0000x + 5.0000")
print(f"  R²: {s['r_squared']:.4f}")
print(f"  残差 std: {s['residual_std']:.2f} (真实噪声 ~3)")
print(f"  结构断层: {s['structure_gaps']} 次")

fl_err_avg = sum(errors_fl[-100:]) / 100
print(f"  近100轮平均误差: {fl_err_avg:.3f}")

# 关键断言
a_err = abs(s['a'] - 2.0)
b_err = abs(s['b'] - 5.0)
print(f"\n  a 误差: {a_err:.4f} {'✅' if a_err < 0.1 else '⚠️'}")
print(f"  b 误差: {b_err:.4f} {'✅' if b_err < 0.1 else '⚠️'}")
print(f"  R²: {s['r_squared']:.4f} {'✅ >0.99' if s['r_squared'] > 0.99 else '⚠️'}")

# ── 结构断层测试: y=2x+5 → y=10x+0 (极端突变) ──
print(f"\n--- 结构断层测试: y=2x+5 → y=10x+0 ---")
for x in range(500, 550):
    y_obs = 10 * x + 0 + random.gauss(0, 8)
    fl.update(x, y_obs)
    if fl.structure_gap():
        print(f"  ⚡ structure_gap 触发于 x={x}")
    if x in [505, 520, 549]:
        print(f"  x={x}: theta=[{fl.theta[0]:.2f}, {fl.theta[1]:.1f}]")

print(f"结构断层: {fl.structure_gaps} 次 {'✅' if fl.structure_gaps > 0 else '⚠️'}")
print(f"最终: y = {fl.theta[0]:.3f}x + {fl.theta[1]:.1f} (目标: 10x+0)")
