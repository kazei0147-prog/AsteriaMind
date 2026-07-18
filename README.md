# AsteriaMind (formerly HiveMind)

**AsteriaMind 是一个探索多个智能体如何组织、适应和共同演化的实验性项目。
一种基于贝叶斯信念与论证评估的自组织认知系统架构**

> v0.1-v0.6: **HiveMind** (存档) — 预设偏见 + 能量经济 + 加权平均  
> v2.0+: **AsteriaMind** — 可学习偏见 + 论证评估 + 验证信任 + 四层自治探索

---

## 一、摘要

HiveMind 是一套**不依赖中心化大模型、不依赖持续高算力投入**的认知系统架构。

它的核心假设是：

> **如果一群具有不同偏见倾向的独立推理节点，在严格的能量预算约束下，通过时间迭代、横向交流、离线反思和渐进式替换来形成共识——那么这套系统能够以极低的边际成本，在长期时间尺度上逼近复杂问题的可靠答案。**

它不是“更快的推理器”，而是 **“更耐久的推演生态”**。

---

## 二、系统定位

**本系统不为“即时问答”而生。**

它服务于以下场景：

- 缺乏稳定网络和云计算资源的边缘环境
- 需要长期推演、无法用一次性判断解决的复杂问题
- 希望拥有独立认知能力、不愿依赖外部AI服务的组织或个人

**一句话概括：**

> **用时间置换算力，用内部制衡置换外部依赖。**

---

## 三、架构总览 / Architecture Overview

AsteriaMind v2.x 的架构围绕一个核心原则组织：**Learner 自由思考 → MotherMind 综合决策 → Guard 只护架构。**

```
                   ┌─────────────────────────────┐
                   │          Portal             │  ← I/O 层
                   │  DataSource  │  OutputSink  │     (数据进, 决策出)
                   └──────┬──────────────┬───────┘
                          │ poll         │ emit
                   ┌──────▼──────────────▼───────┐
                   │      CuriosityEngine        │  ← 注意力层
                   │  检测异常 → 触发探索          │
                   └──────────────┬──────────────┘
                                  │
                   ┌──────────────▼──────────────┐
                   │        MotherMind           │  ← 决策层
                   │  读推理 → 综合 → 解释 → 反馈   │
                   └──────┬──────────────────────┘
                          │
    ┌─────────────────────┼─────────────────────┐
    │                     │                     │
    ▼                     ▼                     ▼
┌───────┐  ┌───────┐  ┌───────┐  ┌───────┐  ┌───────┐
│  L1   │  │  L2   │  │  L3   │  │  L4   │  │  L5   │  ← 认知层
│ opti  │  │ pessi │  │ skep  │  │ stub  │  │ adap  │     5 个 Bayesian Learner
└───────┘  └───────┘  └───────┘  └───────┘  └───────┘
    │         │          │          │          │
    └─────────┴──────────┴──────────┴──────────┘
                      │
          ┌───────────▼───────────┐
          │    BudgetContest      │  ← 资源分配层
          │  Learner 竞标探索资源  │
          └───────────────────────┘
          ┌───────────────────────┐
          │    StabilityGuard     │  ← 安全层
          │  只护架构, 不碰认知     │     (Learner 数量/学习率上限)
          └───────────────────────┘
```

**核心模块 / Core Modules：**

| 模块 / Module | 文件 / File | 职责 / Role |
|---|---|---|
| **MotherMind** | `mother.py` | 决策者 — 阅读每个 Learner 的推理链, 综合形成判断, 产生带解释的决策, 反馈给 Learner |
| **Learner ×5** | `learner.py` | 认知节点 — 贝叶斯信念从经验中学习, 无预设偏见. 每个有独立的先验、窗口、尺度追踪器 |
| **Portal** | `portal.py` | I/O 层 — DataSource(CSV/Live/Search) + OutputSink(Console/Log) + CuriosityEngine(6 触发器) |
| **FunctionLearner** | `function_learner.py` | 结构学习 — RLS 在线线性回归, 学 y=ax+b, 检测结构断层(structure_gap) |
| **BudgetContest** | `budget_contest.py` | 资源竞标 — 竞标制探索资源分配(垄断惩罚 + 10% 随机打破茧房) |
| **TrustEngine** | `trust.py` | 信任评估 — 自适应阈值(噪声地板基线), 事后验证准确率决定信任 |
| **StabilityGuard** | `guard.py` | 架构保护 — 仅检查 Learner 数量/学习率上限等不变量, 绝不干预认知过程 |
| **CrossValidator** | `validator.py` | 静默期交叉验证 + 隔离状态机 — 诊断搭便车/共识拖累, 自动隔离问题 Learner |
| **ExplorationReward** | `exploration_reward.py` | 探索奖励 — 延迟验证队列 + 三项加权(事后验证/稳定性/共识偏离) |
| **MotherAdapter** | `mother_adapter.py` | Mother→Learner 反馈适配器 — 自然语言→可执行指令(窗口/Student-t/学习率) |
| **PolyLearner** | `poly_learner.py` | 多项式 RLS 自动升阶 — 检测结构崩塌, 1→2→3 次自动升级 |
| **MetaLearner** | `meta_learner.py` | 多基函数选择 — 多项式/Fourier/指数, Bayesian 选最优基, 协方差崩塌自动重置 |
| **DiagnosticEngine** | `diagnosis.py` | 三假说诊断 — 函数变化/噪声增大/分布偏移, ExperimentDesigner 靶向采样 |
| **ToolRegistry** | `tool_registry.py` | 工具注册中心 + MotherMind 自主编排 — 状态驱动的工具调用链 |
| **KnowledgeGraph** 🔬 | `knowledge.py` | v3.0 知识表征 — 实体/关系/信念图, 查询/推理/缺口检测/Curiosity 挂载 |

## 四·五、v3.0-alpha: Knowledge Core — 脑内世界

> 🔬 **实验性。** 从"数值模式识别"升级为"结构化知识表征"。

**核心转变：她不再只是在数据里找规律，而是在脑子里建世界。**

| 元素 | 说明 |
|------|------|
| **Entity** | 概念节点: "y=2x+5", "线性函数", "导数" |
| **Relation** | 带类型的关系: IS_A, HAS_PROPERTY, DERIVATIVE_OF |
| **Belief** | 每条关系带 Bayesian 置信度, 可被验证/修正 |
| **Query** | 自然语言问: "y=2x+5 的导数是什么?" |
| **Gap Detection** | 自动发现知识缺口: "这家伙只有 1 条关系, 我不了解它" |
| **Inference** | 传递推理: A→B 且 B→C → A→C |
| **Curiosity Hook** | 最不确定的知识 → Curiosity 优先验证 |

**下一阶段 (v3.0+):**
- [ ] Learning Pipeline (文本 → 概念 → 关系 → 假说 → 验证 → 入库)
- [ ] Skill Library (缺口 → 生成技能 → 测试 → 保存)

**v0.x 存档 / v0.x Archive：** 旧的 HiveMind v0.6（能量经济 + 预设偏见 + 加权平均）代码保留在 [`src/hivemind/`](src/hivemind/), 失败复盘见 [`docs/WHY_HIVEMIND_FAILED.md`](docs/WHY_HIVEMIND_FAILED.md).

---

## 四、核心机制 / Core Mechanisms

AsteriaMind v2.x 的核心机制与 v0.x 完全不同。v0.x 的核心是"预设偏见 + 加权平均 + 能量竞争"——已被 11 组实验证明在真实数据上不可靠。v2.x 的每条机制都是对 v0.x 失败的逐一修正。

### 4.1 贝叶斯信念学习 / Bayesian Belief Learning

> 替代 v0.x 的预设偏见（α×1.3, β×0.7, δ 反向…）

每个 Learner 维护一个贝叶斯先验 N(μ, σ), 从 N(0, 10) 起步, **无预设偏见**。通过观测数据持续更新 μ 和 σ:

- **方案 A (默认):** 尺度归一化 — 误差按 `data_scale` 归一化后更新, σ 双向调整(可增可减)
- **方案 B (可选):** Student-t 鲁棒似然 — 天然阻尼极端离群值（error=5000 → μ 仅漂移 0.01, 旧版漂移 50）
- **ScaleTracker:** EMA 追踪数据尺度, 检测 regime change, 自动适配任意数据范围
- **差异化先验:** 五个 Learner 初始 μ∈{+3, -3, 0, 0, 0}, σ∈{12, 12, 20, 3, 10} — 不同性格从起点就分化

**Benchmark 验证:** CO2 数据上 μ 稳定收敛, 尺度跳变 10→500 后 σ 自动从 10 增长到 27。旧版在 error=5000 时 μ 直接漂移 50。

### 4.2 论证评估共识 / Argument-based Consensus

> 替代 v0.x 的加权平均共识

不再是 `weighted_avg(proposals)`。每个 Learner 提案时附带**推理链**（数据窗口 + 历史准确率 + 置信区间）。MotherMind 评估"谁的论证更站得住脚", 而非"谁的 confidence 权重更大":

1. 提案: Learner → ReasoningChain(proposal, confidence, data_window, history)
2. 讨论: 提案互看 → 修正 → 评估 → 排序
3. 决策: MotherMind 产出 Decision(consensus, dominant_learner, dissenting_views, reservations, per-learner feedback)

**与 v0.x 的本质差异:** v0.x 的共识是数学运算; v2.x 的共识是"最佳解释的识别"。

### 4.3 验证精度信任 / Verification-based Trust

> 替代 v0.x 的采纳计数信任（adoption_count）

信任不再来自"被采纳了多少次"。而是**事后验证的准确率**:

- 每轮讨论后, 用预留的验证数据评估每个 Learner 的提案
- 准确 → trust↑; 持续偏差 → trust↓
- trust 高的 Learner 在论证评估中自然获得更大权重
- 这不是写死的——trust 会随着 Learner 的实际表现动态变化

**Benchmark 验证:** 多传感器故障测试中, 故障 Learner 的 trust 在 30 轮内从 0.5 降到 0.15, 共识从 16.81 ppm(简单平均) 降至 3.81 ppm。

### 4.4 函数结构学习 / Function Structure Learning

> v2.8 新增, 解决"Learner 只会学偏差, 不懂规律"的根问题

**FunctionLearner** 使用在线递推最小二乘(RLS), 增量学习 x-y 函数关系 y=ax+b:

- 无需存储全量历史, 低算力
- 自动检测结构断层(structure_gap): 当 R² 骤降或预测误差超 3σ → 标记"函数规律已改变"
- structure_gap 是 CuriosityEngine 的第五个触发器

**Benchmark 验证:** y=2x+5, 200 轮噪声数据后学到 a=2.0038 (误差 0.19%), R²=0.9912。外推 x=1000 → 2008.78 (真值 2005)。

### 4.5 四层自治探索 / Four-layer Autonomous Exploration

> v2.9, 完整替代 v0.x 的能量经济 + 梦境

系统不是"给任务 → 推理 → 停"。而是持续运行, 自主决定何时探索、探索什么:

| 层 / Layer | 模块 / Module | 职责 / Role |
|---|---|---|
| **L1 注意** | CuriosityEngine | 检测异常(residual/sigma/structure_gap/stale/low_confidence/knowledge_gap) |
| **L2 驱动** | Learner.exploration_drive() | 每个 Learner 自己产生探索欲(uncertainty × surprise × novelty) → ExplorationProposal |
| **L3 竞标** | BudgetContest | score=value×track_record/cost, 垄断惩罚(÷streak-1), 10% 随机打破茧房 |
| **L4 兜底** | MotherMind fallback | 当无 Learner 提案时, 系统级生成探索 query |

此外, CuriosityEngine 保留 6 个触发器:
1. `stale` — 数据陈旧
2. `low_confidence` — 共识不确定
3. `learner_sigma` — 某 Learner 高度不确定
4. `knowledge_gap` — 连续低置信
5. `structure_gap` — 函数结构突变 (v2.8)
6. `search_requested` — Learner 主动请求搜索 (v2.9)

### 4.6 架构保护 / Stability Guard

> v2.3 重构 — 只保护架构, 绝不干预认知

Guard 不参与学习回路, 不冻结 Learner, 不压制异见。它只检查**绝对不变量**:

| 不变量 / Invariant | 上限 / Limit |
|---|---|
| Learner 数量 | 10 |
| 学习率 | 0.5 |
| 讨论轮次 | 5 |
| 信任下限 | 0.01 |

违反时记录 warning, 不改变认知过程。Guard 保护的是**系统结构**, 不是**系统观点**。

### 4.7 梦境记忆 / Dream Memory

> v2.1 — 轻量 checkpoint, 替代 v0.x 的蒸馏引擎

每个 Learner 的状态(μ, σ, track_record, scale_tracker)可序列化为 JSON(~1.5KB), 保存为 checkpoint。热启动加载后:

- 蒸馏效率提升 9.9×（loss 0.79 → 0.08 ppm）
- 无需重训练, 直接延续上次的认知状态
- 跨数据集可迁移

---

## 五、设计哲学 / Design Philosophy

AsteriaMind 不是对现有 AI 范式的改良，而是从 v0.6 的失败中提取出的**已验证原则**。v0.x 的教训（详见 [`WHY_HIVEMIND_FAILED.md`](docs/WHY_HIVEMIND_FAILED.md)）直接塑造了 v2.x 的每一条设计选择。

| v0.x 原则（❌ 已验证失败） | v2.x 原则（✅ 已验证可行） | 失败原因 → 修正方式 |
|---|---|---|
| 预设偏见（α×1.3, β×0.7…） | 偏见从经验中涌现 | 写死的系数在真实数据上不成立 → 贝叶斯信念自由更新 |
| 加权平均共识 | 论证评估共识 | CO2 误差 31.69 ppm → 1.07 ppm |
| 采纳计数 = 信任 | 事后验证准确率 = 信任 | 故障传感器持续被采纳 → 污染共识 8× |
| 能量决定谁活谁死 | 解释力决定谁更被信任 | 能量衡量活跃度, 不衡量正确性 |
| 中央调度 → 子模块执行 | Learner 自主产生探索欲 → 竞标 | Mother 不是传话筒, Learner 不是傀儡 |
| 硬抑制异见 | 架构保护, 认知自由 | Guard 冻结学习 → Learner 不敢出头 |

**两条不变的核心信念：**

> **1. "用时间置换算力，用内部制衡置换外部依赖。"**  
> 五个 Learner 在无 GPU、无大模型、无云服务的条件下，仅靠贝叶斯更新 + 论证评估 + 连续验证，能在 CO2 时序和传感器故障场景中超越简单统计基线。

> **2. "一个系统能承受的最强压力，不是外部攻击，而是内部闲置。"**  
> CuriosityEngine + BudgetContest + autonomous search 回路确保系统不会"停在那里等任务"——它在持续寻找下一个值得问的问题。

**v0.x 是台阶，v2.x 是阶梯。** v0.6 用 11 组实验换来的不是失败，是一张"什么不能做"的地图。AsteriaMind 从那张地图的另一侧出发。

---

## 六、当前状态

**v2.9：四层自治探索 — Learner自由驱动探索、BudgetContest竞标、MotherMind编排。**

v0.x (存档):
- [x] v0.1-v0.6: 从双模块到知识蒸馏引擎 → [`src/hivemind/`](src/hivemind/)
- [x] 11 组实验验证 + WHY_HIVEMIND_FAILED.md 失败复盘

v2.x (当前):
- [x] v2.0 : 学习式共识 (贝叶斯信念替代预设偏见, CO2 benchmark 1.07 ppm)
- [x] v2.1 : 差异化先验 + 梦境记忆 (checkpoint 保存/加载, 热启动 9.9× 提升)
- [x] v2.3 : MotherMind 决策者 + Guard 纯架构保护
- [x] v2.4 : Portal I/O + 好奇心驱动持续运行
- [x] v2.5 : 自主搜索回路 (knowledge_gap → MotherMind query → WebSearch)
- [x] v2.6 : ScaleTracker + 尺度自适应 (方案A: 归一化, 方案B: Student-t)
- [x] v2.7 : 完全自主探索 (knowledge_gap streak fix + MotherMind query)
- [x] v2.8 : FunctionLearner RLS (y=2x+5 → a=2.0038, R²=0.9912)
- [x] **v2.9 : 四层自治探索** (Learner.drive → BudgetContest → Winner → MotherFallback)
- [x] v2.10: 死锁修复 + CrossValidator 静默期 + 自适应 trust + 隔离状态机 (2026-07-17)
- [x] v2.10: 探索奖励引擎 (延迟验证 + 三项加权合成)
- [x] v2.10: Mother→Learner 反馈回路 (窗口/Student-t/学习率)
- [x] v2.10: Curiosity 探索耐心 + 定期自主实验
- [x] v2.10: PolyLearner 自动升阶 (RLS 1→2→3 次多项式)
- [x] v2.10: MetaLearner 多基选择 (多项式/Fourier/指数)
- [x] v2.10: DiagnosticEngine 三假说诊断 (函数/噪声/分布)
- [x] v2.10: ToolRegistry + MotherMind 自主编排
- [x] v2.10: Curiosity 主动信号 (knowledge_frontier + R²_decline)
- [x] **v3.0-alpha: KnowledgeGraph** (实体/关系/信念知识表征)
- [ ] Learning Pipeline (文本→概念→关系→假说→验证→入库)
- [ ] Skill Library (缺口→生成→测试→保存)

> ⚠️ **v0.6 的诚实复盘**：真实数据（exp09-11）暴露出 v0.1-v0.6 "固定偏见加权平均 + 采纳计数信任" 在漂移/污染数据下不可靠。完整复盘见 [`docs/WHY_HIVEMIND_FAILED.md`](docs/WHY_HIVEMIND_FAILED.md)，重构方向见下方 v2.0 alpha。

---

## 六·五、HiveMind 2.0 alpha（实验性新架构）

> ⚠️ 实验性分支，与 v0.6 主架构（`src/hivemind/`）**并存、不替代**。代码在 [`src/hivemind_v2/`](src/hivemind_v2/)。

v0.6 在真实数据上暴露的根本问题（共识被漂移/污染数据绑架），促成了一次共识机制的彻底重构：

| 维度 | v0.1–v0.6 | v2.0 alpha |
|------|-----------|------------|
| 信念来源 | 预设 bias_type（开拓/守门/外交/纠错） | 从经验学**贝叶斯信念**（`learner.py`） |
| 共识机制 | 固定偏见的加权平均 | **论证评估** ArgumentEvaluator（`argument.py`） |
| 信任依据 | 采纳计数 adoption_count | **验证精度**（`trust.py`） |
| 主循环 | 推演→提议→加权→共识 | **预热 + 讨论 + 验证**（`orchestrator.py`） |

**Benchmark（Mauna Loa CO2, 406–432 ppm）：**

| 架构 | 误差 | 结论 |
|------|------|------|
| v0.6 | 31.69 ppm | ❌ 固定偏见加权在真实缓变信号上失效 |
| **v2.0 alpha** | **1.07 ppm** | ✅ 优于移动平均（1.42 ppm） |

目前 v2.0 处于 alpha 验证（单 benchmark 通过），尚未替代主架构。运行：`cd src && python bench_v2.py`。

---

## 七、快速开始（MVP）

```bash
# 安装
pip install -e .          # 通过 pyproject.toml 安装
pip install matplotlib    # 可选，用于图表生成

# 运行仿真（200轮默认参数）
cd src && python runner.py --rounds 200 --target 50

# 自定义参数
cd src && python runner.py --rounds 500 --target 50 --noise 15 \
    --adoption-reward 10 --inference-cost 6 --energy-floor 5 \
    --decay-rate 0.05 --output ./my_experiment

# 2000轮长期验证（预设脚本）
cd src && python longterm_validation.py

# 生成图表
cd src && python visualize.py --input ../experiments/exp01_default_convergence \
    --output ../experiments/exp01_default_convergence
```

核心模块一览（[`src/hivemind/`](src/hivemind/)）：

| 文件 | 模块 | 说明 |
|------|------|------|
| `config.py` | HiveMindConfig | 可调参数 |
| `energy.py` | EnergyWallet | 能量会计（支出/收入/借贷/挣扎线） |
| `submodule.py` | Alpha + Beta + Gamma + Delta + Epsilon | 开拓者 + 守门人 + 外交官 + 纠错者 + 幸存者（懒加载）|
| `distill.py` | DistilledModel + DistillationEngine | 知识蒸馏引擎（特征提取 + 逻辑回归 + checkpoint）|
| `datasource.py` | DataSource + CSV + Multi + Noisy | v0.6 数据源抽象层（插拔式，支持 CSV/API/多源/噪声）|
| `consensus.py` | ConsensusTracker | 共识追踪（值 + 累积置信度衰减 + 历史） |
| `fallback.py` | FallbackController | 保底机制（影子候选） |
| `dream.py` | DreamMechanism | 梦境（蒸馏 + 杂交） |
| `death.py` | DeathProtocol | 临终协议（遗产胶囊） |
| `mother.py` | MotherModule | 母模块调度中心 |

实验记录（[`experiments/`](experiments/)）：

| 目录 | 实验 | 轮数 | 关键发现 |
|------|------|------|----------|
| `exp01_default_convergence` | v0.1 默认参数 | 200 | 完美收敛（误差 0.14） |
| `exp02_stress_test` | v0.1 高噪声+低奖励 | 200 | 双模块破产，系统崩溃 |
| `exp03_longterm_validation` | v0.1 中等压力 | 2000 | alpha 第38轮成僵尸，结构性缺陷 |
| `exp04_alpha_rescue` | v0.1 调参救活 alpha | 500 | alpha 第65轮仍死，确认缺 beta |
| `exp05_beta_validation` | v0.2 三模块中等压力 | 2000 | 修bug成功（fallback 12次），但低奖励下beta/gamma 死 |
| `exp05b_beta_favorable` | v0.2 三模块高奖励 | 2000 | **3模块全部存活2000轮** |
| `exp06_four_module_validation` | v0.3 四模块中等奖励 | 2000 | 4模块全活但都挣扎（reward=15不够分） |
| `exp06b_four_module_favorable` | v0.3 四模块高奖励 | 2000 | **4模块全部健康存活2000轮**（注：此实验在 v0.3.1 角色互换前运行，当时 gamma=反共识、delta=复合型） |
| `exp07_distillation_validation` | v0.4 蒸馏引擎验证 | 2000 | 8000样本 82轮蒸馏 loss=4.35e-5 checkpoint=512 bytes |
| `exp08_five_module_curiosity` | v0.5 五模块+好奇心 | 2000 | 5模块 好奇心584轮 表达389轮 epsilon生命周期 |
| `exp09_real_data_source` | v0.6 真实数据 | 1038 | 全球温度异常数据 4/5存活 自适应奖励 蒸馏反馈 |
| `exp10_checkpoint_compare` | v0.6 Checkpoint对比 | 1038 | 冷vs热启动 蒸馏效率提升2.1×（loss 0.0004→0.00019） |
| `exp11_sensor_fault` | v0.6 传感器故障压测 | 400 | 无外部校验 → 污染数据绑架共识，误差放大~8倍（催生 v2.0） |
| `bench_v2_co2` | v2.0 CO2 benchmark | 400 | 贝叶斯共识 1.07 ppm (vs v0.6 31.69, vs 移动平均 1.42) |
| `bench_multisensor` | v2.0 多传感器容错 | 400 | 故障传感器 HM 3.81 vs 简单平均 16.81 (4.4×) |
| `bench_learn_calc` | v2.8 学公式+计算 | 200 | y=2x+5 → a=2.0038, R²=0.99, x=1000→2008.78 |
| `test2_budget` | v2.9 BudgetContest | 50 | 竞标 72/24/4% 分配 + 16% 随机探索 ✅ |
| `test3_evolution` | v2.9 长期演化 | 400 | 4/4 胜者多样性 + 33 竞标 ✅ |
| `test4_interference` | v2.9 干扰测试 | 350 | 故障期 4.0 vs 正常 2.8 提案/轮 ✅ |

完整实验报告见 [`docs/EXPERIMENT_LOG.md`](docs/EXPERIMENT_LOG.md)。

---

## 许可证声明

本文档采用 **CC BY-NC 4.0** 精神：

- ✅ 允许转载、引用、讨论
- ✅ 允许基于本文档进行非商业性质的重构与衍生
- ❌ 禁止用于任何商业目的或封闭源代码的专有系统
- 📌 转载或引用时，必须保留作者署名（kazei0147-prog）

（GitHub 许可证列表未收录 CC BY-NC 4.0，特此补充声明）

---

## 十、致谢

- **DeepSeek 与 腾讯元宝（Yuanbao）**：在漫长的推演对话中，协助将直觉性的构想转化为可表述的架构，并帮助定位了耗散结构等理论参照系。

- **Ilya Prigogine（1917–2003）**：其耗散结构理论为本文对“系统在远离平衡态下自组织演化”的思考提供了重要的科学背景。需要说明的是，作者是在推演过程中经讨论了解到这一理论框架的，而非在构思之初即已引用。

---

*Last updated: 2026-07-18 (v3.0-alpha: KnowledgeGraph — entity/relation/belief knowledge core)*
