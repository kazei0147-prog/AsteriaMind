"""
v2.8 实战: 学习 y=2x+5, 然后计算 x=1000 时的 y
"""
import sys, random
sys.path.insert(0, "D:/AM/HiveMind_repo/src")
from AsteriaMind.function_learner import FunctionLearner

random.seed(42)
fl = FunctionLearner(dim=2, forgetting=0.995)

print("=" * 60)
print("📐 HM 学数学: y = 2x + 5 + noise")
print("=" * 60)

# ── 学习阶段: 200 轮 ──
print("\n[学习阶段] 喂入 200 个样本...")
for x in range(200):
    y_obs = 2 * x + 5 + random.gauss(0, 3)
    fl.update(x, y_obs)

s = fl.summary()
print(f"  学到的公式:   y = {s['a']:.4f}x + {s['b']:.4f}")
print(f"  目标公式:     y = 2.0000x + 5.0000")
print(f"  a 误差:       {abs(s['a']-2):.5f}")
print(f"  b 误差:       {abs(s['b']-5):.4f}")
print(f"  R²:           {s['r_squared']:.4f}")
print(f"  残差标准差:   {s['residual_std']:.2f} (噪声 ~3)")

# ── 内推验证 ──
print("\n[验证阶段] 用学到的公式计算已知点...")
for x_test in [0, 10, 50, 100, 199]:
    y_pred = fl.predict(x_test)
    y_true = 2 * x_test + 5
    print(f"  x={x_test:3d}:  预测={y_pred:8.2f}  真实={y_true:8.2f}  误差={abs(y_pred-y_true):6.3f}")

# ── 外推: 计算 x=1000 ──
print("\n[外推阶段] 🎯 计算从未见过的 x=1000...")
y_1000 = fl.predict(1000)
y_true_1000 = 2 * 1000 + 5
print(f"  HM 的答案:    y = {y_1000:.2f}")
print(f"  正确答案:     y = {y_true_1000:.2f}")
print(f"  误差:         {abs(y_1000 - y_true_1000):.2f}")
print(f"  相对误差:     {abs(y_1000 - y_true_1000)/y_true_1000*100:.3f}%")

# ── 结论 ──
print()
a_err = abs(s['a'] - 2.0)
b_err = abs(s['b'] - 5.0)
extrap_err = abs(y_1000 - y_true_1000)

if a_err < 0.01 and b_err < 0.5 and extrap_err < 10:
    print("✅ HM 学会了 y=2x+5, 并能准确外推到 x=1000")
elif a_err < 0.05:
    print("⚠️  HM 学到了近似公式, 外推有轻微偏差")
else:
    print("❌ HM 没能学会")
