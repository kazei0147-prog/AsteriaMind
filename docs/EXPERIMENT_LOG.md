# HiveMind Experiment Log

**Researcher**: kazei0147-prog + AI collaboration  

---

## v0.1 Experiments (alpha + gamma only, no beta)

See experiments 1-4 above for full v0.1 results.

**v0.1 Summary**:
1. **Missing beta is a structural defect** — parameter tuning alone cannot stabilize the system
2. **Energy floor creates zombies** — alive but unable to act is worse than genuinely dead
3. **Confidence decay is ineffective** — it only triggers when no proposals exist, which never happens
4. **Counter-consensus needs an opponent** — without alpha, gamma oscillates against itself

---

## v0.2 Experiments (alpha + beta + gamma, three-module architecture)

**Date**: 2026-07-02  
**Version**: v0.2 — Added beta (conservative) module + fixed two structural bugs  

### v0.2 Bug Fixes

1. **Energy floor zombie fix**: Floor is now a "struggling line", not a "zombie line"
   - Modules CAN spend below floor (floor only marks `struggling=True`)
   - Struggling modules have confidence halved but still act
   - Modules die only when balance ≤ 0 (no more zombies)
2. **Confidence decay fix**: Cumulative decay + partial recovery (not full reset each round)
   - 70/30 blend: 70% from decayed history + 30% from current proposals
   - Stagnation penalty: 3x decay rate when change_rate < threshold
   - Fallback mechanism now actually triggers
3. **Reward distribution fix**: Proportional rewards by confidence weight (not equal sharing)
   - High-confidence modules earn more (competitive economics)
   - Prevents the "N modules = 1/N reward each" death spiral

---

## Experiment 5: Medium Stress — Three Module Validation (2000 rounds)

**Purpose**: Direct comparison with exp03 (same parameters, now with beta).

| Parameter | Value | Note |
|-----------|-------|------|
| Rounds | 2000 | Same as exp03 |
| Target | 50 | Same |
| Noise | 15 | Same |
| Adoption Reward | 6 | Same (low reward) |
| Inference Cost | 5 | Same |
| Confidence Decay | 0.05 | Same |
| Energy Floor | 10 | Same (now struggling line, not zombie line) |

**Key Results**:

| Checkpoint | Consensus | Error | Alive | Struggling | Fallbacks |
|-------------|-----------|-------|-------|------------|-----------|
| 100 | 75.19 | 25.19 | 1 | 2 | 0 |
| 500 | 78.06 | 28.06 | 1 | 2 | 0 |
| 1000 | 56.61 | 6.61 | 1 | 2 | 0 |
| 1500 | 69.03 | 19.03 | 1 | 2 | 0 |
| 2000 | 68.75 | 18.75 | 1 | 2 | 12 |

- alpha: survived all 2000 rounds (balance=1520, very healthy)
- beta: **died at round 49** (adopted=49, insufficient reward when shared among 3)
- gamma: **died at round 49** (same issue)
- Fallback triggered: **12 times** (previously 0 in all v0.1 experiments!)
- Dream triggered: 300 times
- Confidence: 0.53 (previously stuck at ~1.0)

**Observations**:
- The three structural bugs are confirmed fixed: fallback triggers, no zombies, confidence decays
- But reward=6 with 3 modules is still unsustainable: proportional share gives each module ~2, cost=5
- Beta and gamma both died quickly because proportional rewards can't cover costs at low reward
- **alpha survives alone** because when beta/gamma die, it gets full reward=6 > cost=5

**Files**: `experiments/exp05_beta_validation/`

---

## Experiment 5b: Favorable Conditions — Three Module Survival (2000 rounds)

**Purpose**: Test beta module under favorable economics (reward=15, same as v0.1 exp01).

| Parameter | Value | Note |
|-----------|-------|------|
| Rounds | 2000 | Extended from exp01's 200 |
| Target | 50 | Same |
| Noise | 10 | Favorable |
| Adoption Reward | 15 | High reward (same as exp01) |
| Inference Cost | 5 | Same |
| Confidence Decay | 0.02 | Favorable |
| Energy Floor | 10 | Struggling line |

**Key Results**:

| Checkpoint | Consensus | Error | Alive | Struggling |
|-------------|-----------|-------|-------|------------|
| 100 | 60.75 | 10.75 | 3 | 0 |
| 500 | 51.73 | 1.73 | 3 | 2 |
| 1000 | 44.45 | 5.55 | 3 | 2 |
| 1500 | 53.63 | 3.63 | 3 | 2 |
| 2000 | 46.17 | 3.83 | 3 | 2 |

- **alpha**: alive, adopted=2000, balance=2.7, struggling=True
- **beta**: alive, adopted=2000, balance=2434.7, struggling=False — **dominant earner**
- **gamma**: alive, adopted=2000, balance=2.7, struggling=True
- Fallback: 0, Dream: 400, Deaths: 0
- **ALL THREE MODULES SURVIVED 2000 ROUNDS!**

**Observations**:
- Beta is the **anchor**: its conservative anchor (0.6 trust in consensus) makes its proposals closest to consensus → highest proportional reward
- Beta accumulates enormous energy (2434) while alpha and gamma hover near the struggling line
- The system oscillates around target (46→53→44→53) but never collapses
- Error remains moderate (3-6) throughout — **not perfect but stable**
- **v0.1 exp03 vs v0.2 exp05b**: from 1 module surviving (zombie) to 3 modules alive (2 struggling but active)

**Critical Insight**: The reward distribution economics determine module survival:
- reward >> cost × N_modules → all survive
- reward ≈ cost × N_modules → edge case, some struggle
- reward < cost × N_modules → module death spiral
- Beta earns the most because its proposals are closest to consensus (anchor effect)

**Files**: `experiments/exp05b_beta_favorable/`

---

## v0.2 Summary

### Confirmed Fixes
1. **Energy floor → struggling line**: No more zombies. Modules at floor can still act (with reduced confidence)
2. **Confidence decay → cumulative**: Fallback now triggers (12 events in exp05)
3. **Reward distribution → proportional**: High-confidence modules earn more (competitive economics)

### Confirmed Architectural Value
- **Beta is the anchor**: Under favorable economics, beta dominates earnings by staying close to consensus
- **Three-module survival**: All modules survived 2000 rounds in exp05b (vs alpha zombie in v0.1)
- **System stability**: No single-module collapse, no zombie oscillation

### Remaining Issues
1. **Low reward economy**: When reward < cost × modules, multi-module survival fails → need better reward scaling
2. **Alpha/Gamma always struggling**: Their biases push them away from consensus, earning less proportionally
3. **Confidence still above fallback threshold**: In favorable conditions, confidence stays at 0.7, fallback never triggers

### Next Steps (v0.3)
1. Consider reward scaling: total_reward ∝ number_of_active_modules (more modules = more total reward)
2. Consider "rebirth" mechanism: modules that die can restart with seed energy from system reserve
3. Run stress test with three modules (high noise, low reward) to test resilience
4. Explore adaptive bias: modules that are consistently struggling should reduce their bias

---

> v0.1 experiments were conducted using the HiveMind v0.1 MVP prototype (alpha + gamma only).  
> v0.2 experiments use the three-module architecture (alpha + beta + gamma).  
> All charts and raw data are included in the `experiments/` subdirectories.
