"""尺度跳变测试: 10 → 500"""
import sys, random
sys.path.insert(0, "D:/AM/HiveMind_repo/src")
from hivemind_v2.learner import Learner, BayesianBelief

random.seed(42)
l_new = Learner("v2.6", initial_mu=0, initial_sigma=10, window_size=5,
                adaptive_scale=True, robust_likelihood=True)
l_old = BayesianBelief(mu=0, sigma=10, adaptive_scale=False)

print("=== 尺度跳变: 10 → 500 ===")
print(f"{'epoch':>5s}  {'new_mu':>9s}  {'new_s':>6s}  {'scale':>7s}  {'old_mu':>9s}  {'old_s':>6s}")
print("-" * 55)

for epoch in range(150):
    if epoch < 50:
        obs = 10 + random.gauss(0, 2)
    else:
        obs = 500 + random.gauss(0, 20)

    l_new.observe(obs)
    prop = l_new.propose(obs).proposal_value
    l_new.learn(obs, prop)

    err = (obs + l_old.sample()) - obs
    l_old.update(err, 0.1)

    if epoch in [0, 49, 50, 51, 100, 149]:
        tag = " << JUMP" if epoch == 50 else ""
        print(f"{epoch:5d}  {l_new.belief.mu:+9.4f}  {l_new.belief.sigma:5.2f}  "
              f"{l_new.scale_tracker.scale:6.1f}  {l_old.mu:+9.4f}  {l_old.sigma:5.3f}{tag}")

print()
s = l_new.scale_tracker.scale
print(f"v2.6: mu={l_new.belief.mu:+.4f} sigma={l_new.belief.sigma:.2f} scale={s:.0f}")
print(f"old:  mu={l_old.mu:+.4f} sigma={l_old.sigma:.3f}")
print()
print(f"{'✅' if s > 50 else '❌'} ScaleTracker 追踪大尺度 ({s:.0f})")
print(f"{'✅' if abs(l_new.belief.mu) < 5 else '⚠️'} v2.6 mu 稳定 ({l_new.belief.mu:+.3f})")
print(f"{'❌ 旧版被大尺度破坏' if abs(l_old.mu) > 10 else '⚠️ 旧版意外存活'}")
