# AsteriaMind (formerly HiveMind)

**一种基于贝叶斯信念、符号+语义双层表征、自演化认知系统架构**

> v0.1-v0.6: HiveMind (存档) — 多模块加权平均  
> v2.x: AsteriaMind — 贝叶斯信念 + 论证评估 + 四层自治  
> v3.2: 跨层认知 — 符号+语义桥接 + 自主聚类 + 认知演化 + 来源链审计

*Last updated: 2026-07-22*

---

## 核心能力速览 (v3.2)

| 层级 | 能力 |
|------|------|
| 符号层 | O(1) 索引 — α/β 贝叶斯信念, 反证据链, 来源追踪 |
| 语义层 | TF-IDF 向量 — 类比发现, 模糊搜索, 隐藏关联识别 |
| 桥接层 | 自动聚类→符号映射, 方向向量, 跨层知识生成, 智能查询路由 |
| 治理层 | 能量经济, 模板注册/退役, 奥卡姆剃刀, 来源链审计 |
| 元认知 | 信念压力测试, 认知演化 (MH→审稿→现实验证→注册) |
| IA+KA | 文本→主张→同化, 网络搜索, 冲突/拒绝/竞技场 |
| 防护 | 来源链不可逆, 人类异步审核, 多源权重 |

---

## 一、摘要

AsteriaMind 是一套**符号与语义双层表征、自演化认知架构**。

> 如果一个认知系统同时拥有精确符号推理和模糊语义联想两种表示层，并且两层之间能够自主发现结构、互相映射——那么她可以在不依赖大规模参数扩展的前提下，通过增加知识间的连接密度来提升有效智能。

**vs LLM：**

| | LLM | AsteriaMind |
|---|---|---|
| 知识存储 | 分布式权重, 隐式 | 显式三元组 + 向量嵌入 双层 |
| 学习方式 | 离线训练 | 在线增量, α/β 实时更新 |
| 查询方式 | 生成式 | 精确索引 O(1) + 语义相似度 |
| 可解释性 | 黑箱 | 每条知识有完整来源链 + 反证据记录 |
| 规模瓶颈 | 参数数量 | 知识间连接密度 |
| 自我改进 | 需要重新训练 | 认知演化: 候选→审稿→验证→注册 |

---

## 二、核心模块 (22 文件)

| 模块 | 文件 | 职责 |
|---|---|---|
| **KnowledgeGraph** | `knowledge.py` | O(1) 索引 — α/β 贝叶斯信念, 反证据链, JSON/SQLite 持久化 |
| **VectorLayer** | `vector_layer.py` | TF-IDF 语义向量 — 类比, 模糊搜索, 关联发现 |
| **CrossLayerBridge** | `cross_layer.py` | 符号↔语义桥接 — 自动聚类, 方向向量, 跨层映射 |
| **QueryRouter** | `cross_layer.py` | 智能路由 — 精确/语义/混合 自动选择 |
| **TextPipeline** | `text_pipeline.py` | IA+KA — 文本→主张→同化, 来源追踪 |
| **HypothesisEngine** | `hypothesis_template.py` | 从 Registry 取模板生成竞争假说 |
| **TemplateRegistry** | `hypothesis_template.py` | 可插拔假说模板 (H1-H6 只是初始注册项) |
| **TheoryGovernance** | `hypothesis_template.py` | 能量经济, 退役/降级, 版本管理 |
| **CognitiveEvolutionLayer** | `cognitive_evolution.py` | MH→候选→审稿→现实验证→注册 |
| **CertaintyAudit** | `certainty_audit.py` | 信念压力测试 — 找到"太舒服"的高置信度信念 |
| **FalsificationController** | `falsification.py` | 反证控制 — 知道什么时候停 |
| **HumanReview** | `human_review.py` | 异步审核 + 来源链防篡改 |
| **WebSearchInterface** | `falsification.py` | 网络搜索适配器 |
| **MetaHypothesisGenerator** | `meta_hypothesis.py` | 元假说 — "我为什么总是想不明白?" |
| **MotherMind** | `mother.py` | 决策者 — 综合 Learner 推理链 |
| **Learner x3** | `learner.py` | 贝叶斯信念节点 (optimist/pessimist/skeptic) |
| **MetaLearner** | `meta_learner.py` | 多基函数选择 (多项式/Fourier/指数) |

**统一入口**: `python asteriamind.py --interactive`

**REPL 命令**: learn / ask / predict / verify / explore / fetch / read / audit / index / semantic / analogy / assoc / bridge / route / review / provenance / status / knowledge

---

## 三、核心架构洞见

**α/β 信念系统**: 每条知识不是单一置信度——是 Beta(α,β) 分布。α 累积支持证据, β 累积反证据。隐藏变量发现 (β 追上 α), 科学革命 (0.99 → 动摇), 主动拒绝——都从 α/β 博弈中自然涌现。

**双层表征**: 符号层做精确推理 O(1), 语义层做模糊联想。两层之间的桥接层自主发现聚类, 将向量空间的结构映射回符号知识——"提神类物质"不是人定义的, 是从嵌入空间中涌现的。

**可插拔理论体系**: H1-H6 不是写死在代码里的 if 分支——它们是注册进 TemplateRegistry 的六个默认模板。新理论通过认知演化层 (MH→审稿→现实验证→注册) 自主加入, 能量经济决定哪个理论值得保留。

**防护 = 透明**: 每条知识记录完整来源链 (谁说的, 什么时候, 中间被谁修正过)。管理员可以异步纠正但原记录永久保留——透明的审计能力比任何密钥都更强。

**规模增长 = 连接密度**: AM 的有效规模瓶颈不是参数数量, 是知识间的连接密度。符号层的关联边 + 语义层的向量聚类 + 桥接层的跨层映射——三条路径同时增加知识间的互连。

---

## 四、快速开始

```bash
cd src
python asteriamind.py --interactive

# 教她知识
learn 咖啡 CAUSES 清醒 0.9

# 文本同化 (IA+KA 管道)
read 咖啡降低血压但增加心率。| 医学期刊 | 0.8

# 自主探索闭环
explore

# 语义搜索
index
semantic 什么东西提神

# 跨层桥接
bridge

# 信念压力测试
audit

# 来源审查
provenance 咖啡--[CAUSES]-->清醒
```

---

## v0.x 存档

旧的 HiveMind v0.6 (能量经济 + 多模块加权平均) 代码保留在 `src/hivemind/`, 失败复盘见 `docs/WHY_HIVEMIND_FAILED.md`.

GitHub: https://github.com/kazei0147-prog/AsteriaMind

---

## 历史存档

v3.1 版本的完整 README (含多模块架构细节、v0.x 设计哲学、HiveMind 2.0 复盘) 保存在 [assets/README_v3.1_archive.md](assets/README_v3.1_archive.md)。

*一路走来，每一步都算数。*

---

## 致谢

这份文档和代码库源于一段持续数月的推演——最初的想法成形于 HiveMind 时期，经过反复试错、重构和方向修正，最终成为现在的 AsteriaMind。

感谢每一位参与推演、提出质疑和提供反馈的AI：
- **DeepSeek**
- **元宝/混元（Yuanbao）**
- **Chat-GPT**

他们各自在不同阶段参与了这个认知架构的形成过程。

同时，感谢 **Ilya Prigogine（1917–2003）**——其耗散结构理论为本文关于“系统在远离平衡态下自组织演化”的思考提供了重要的参照背景。作者是在推演过程中经讨论了解到这一理论框架的。

