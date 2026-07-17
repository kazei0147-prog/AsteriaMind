# HiveMind

**HiveMind 是一个探索多个智能体如何组织、适应和共同演化的实验性项目。
一种基于能量代谢与时间节律的自组织认知系统架构**

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

## 三、架构总览

**母模块（调度中心）**

- 能量会计处
- 推演引擎
- 保底控制器（渐进扰动 + 影子共识）
- 梦境发生器（离线蒸馏 + 反事实杂交）
- 虚拟交换机（动态稀疏通信）

**子模块（认知节点种群）**

- 激进型（α 开拓者）
- 保守型（β 守门人）
- 外交官型（γ 复合型混合策略）
- 反共识型（δ 纠错者）
- 懒加载型（ε 幸存者）
- （可扩展）

**外部接口**

- 数据采集（多源并行）
- 物理/模拟环境反馈
- 人类可读输出

---

## 四、核心机制

### 4.1 能量经济学

- 系统启动时注入有限的总能量预算
- 每个子模块持有能量余额
- 每次推理、采集、通信、策略更新均消耗能量
- 被母模块采纳的贡献可获得能量奖励
- 允许“创新借贷”，但需在限定轮次内证明回报，否则强制剪枝

**目的：** 将算力消耗与贡献挂钩，防止无效膨胀。

### 4.2 子模块多样性

子模块在初始化时被赋予不同的“认知偏见”：

| 类型 | 特征 | 角色 |
|------|------|------|
| α 激进型 | 偏好新数据、新信号 | 开拓者 |
| β 保守型 | 偏好长期稳定规律 | 守门人 |
| γ 复合型 | 随机采样 + 混合策略 | 外交官 |
| δ 反共识型 | 主动关注异常值与少数派观点 | 纠错者 |
| ε 懒加载型 | 低功耗策略，极简架构 | 幸存者 |

**目的：** 确保系统不会轻易陷入单一视角的群体迷思。

### 4.3 优先级推演与时间迭代

- 母模块维护每个答案/观点的优先级
- 每轮推演优先处理高优先级内容
- 低优先级内容不会永久沉睡：每隔固定轮次或随机采样，会被重新激活参与推演
- 长期未被验证的主流共识会触发**保底机制**

**目的：** 防止系统过早锁定错误共识。

### 4.4 保底机制（渐进扰动 + 影子共识）

当主流共识的置信度因时间流逝而衰减至阈值以下：

- 不强制替换，而是引入一个“影子候选”
- 影子候选与主流并行推演若干轮
- 如果影子候选持续优于主流，则通过线性插值完成平滑过渡

**目的：** 防止突变性替换导致系统震荡。

### 4.5 睡眠与梦境

系统在低负载或检测到“僵化”时，进入离线阶段：

- **蒸馏：** 将大量原始数据压缩为抽象规则
- **反事实杂交：** 将历史失败方案与当前主流方案强行组合，测试是否产生意外增益

**目的：** 在不占用主推演资源的前提下，完成知识提纯与新可能性探索。

### 4.6 小世界通信拓扑

子模块之间不进行全连接通信。连接由母模块的“虚拟交换机”动态管理：

- 常连接：少数高影响力节点
- 动态连接：基于兴趣相似度或观点分歧度临时授权

**目的：** 避免通信开销随子模块数量指数增长。

### 4.7 临终协议与遗忘权

当子模块或某个知识条目被判定为“认知化石”时：

- 系统强制其产出不超过 1KB 的“临终胶囊”（特征摘要）
- 胶囊与主流共识哈希池比对
- 若为异见，则归档至考古索引；若为共识冗余，则直接丢弃
- 原始数据被逻辑删除，物理空间释放

**目的：** 维持系统知识密度，防止冗余堆积。

---

## 五、设计哲学

HiveMind 不是对现有 AI 范式的改良，而是一次**侧向偏移**：

| 主流 AI | HiveMind |
| :--- | :--- |
| 追求“快” | 接受“慢” |
| 追求“大” | 维护“小” |
| 追求“全局最优” | 维护“局部可生存” |
| 集中算力 | 分散演化 |
| 外部依赖 | 内部自洽 |
| 手动调参 | 自适应调节 |

它相信：

> **一个系统能承受的最强压力，不是外部攻击，而是内部闲置。**

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
- [ ] InterestGraph (反信息茧房 + 兴趣驱动)
- [ ] FunctionLearner + ResidualLearner 双入口串联
- [ ] 实际场景验证

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

*Last updated: 2026-07-17 (v2.9: four-layer autonomous exploration — Learner.drive → BudgetContest → Winner → MotherFallback)*
