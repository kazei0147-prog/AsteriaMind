# AsteriaMind (formerly HiveMind)

**一个会呼吸的认知网络——能量在边上代谢，注意力随问题流动，从不丢弃自己的梦**

> v0.1-v0.6: HiveMind (存档) — 多模块竞争 + 能量经济  
> v2.x: AsteriaMind — 贝叶斯信念 + 论证评估  
> v3.2: 跨层认知 — 符号+语义桥接  
> v3.5: 认知闭环 — 双循环学习 + 语言涌现  
> **v3.6: 代谢星图 — Graph Attention + NPMI有向因果网 + 能量代谢 + 梦境内省**

*Last updated: 2026-07-28 — v3.6 metabolic star map*

---

## v3.5 新能力速览

| 层级 | 能力 | 一句话 |
|------|------|--------|
| 🧠 在线学习 | 用户问 → 搜索 → 提取 → 信念更新 → 回答 | 不知道的就搜，搜到就学，学完就答 |
| 🌙 离线学习 | 状态感知自我唤醒 → BudgetContest 选最优探索 | 闲着也不闲，主动补全知识盲区 |
| 🔮 主动推理 | 预测→检索→回复 在线推理链 | 不只被动回答，会主动建议下一步 |
| 🪞 元反思 | 回答→反馈→自我评估→下次更好 | 错了知道为什么错，不再重复 |
| 📖 语言涌现 | 从语料库学句式骨架，语气+内容解耦 | 表达方式随语料增长自然多样化 |
| 🔍 广谱搜索学习 | DuckDuckGo 搜索原句进 language_traces | 不只学事实，也学怎么说 |

---

## 架构总览

```
输入 → Semantic → Pragmatic → ActiveInference → MetaCognition → 回复
         │            │              │                │
         │            │              │                │
    cognitive_    pragmatic      choose_action    weighted_vote
    traces        intent         plan_actions     (学习权重)
         │                           │                │
         └───────────┬───────────────┘                │
                     │                                │
              CognitiveStarMap                  MetaReasoning
              (共现矩阵+语料库)                  (反思→闭环)
                     │
         ┌───────────┼───────────┐
         │           │           │
    OnlineLoop  OfflineLoop  DreamModule
    (用户驱动)  (自我唤醒)  (假说生成)
         │           │
    ActiveLearner ← BudgetContest
    (KG→星图→搜索→用户)
```

---

## 核心设计原则

**不是"改良现有 AI 范式"，是侧向偏移**——用时间置换算力，用内部制衡置换外部依赖。

三元组是骨架，不是终点。被压扁的结构化知识丢掉的信息，由系统的交互机制重新长出来：

| 三元组丢掉的 | 由什么补回来 |
|-------------|-------------|
| 隐含关联 | 共现矩阵 — "企鹅"和"南极"没直接关系，但经常一起出现→边权上升 |
| 不确定性 | ActiveInference Beta 分布 — "我有多确定？有无矛盾证据？" |
| 系统性盲区 | MetaReasoning 反思 — "我总是在鸟类分类上出错" |
| 自然表达 | LanguageGenerator — 从 language_traces 学句式骨架 |
| 未知的未知 | DreamModule — "企鹅的迁徙关系为空，推测与海豹相似" |

---

## v3.5 核心模块

| 模块 | 文件 | 职责 |
|------|------|------|
| **CognitiveStarMap** | `cognitive_star_map.py` | 统一星图 — 三元组痕迹 + 共现矩阵 + 语言痕迹 + 词级共现 + 句式标注 |
| **ActiveInferenceEngine** | `active_inference.py` | 主动推理 — Beta 信念 + free_energy + choose_action + plan_actions |
| **ActiveLearner** | `active_learner.py` | 信息获取 — KG→星图→搜索→用户 四层查询 + 广谱三元组提取 |
| **OfflineLearner** | `offline_learner.py` | 离线学习 — 状态感知自我唤醒 + BudgetContest 竞标 |
| **DreamModule** | `dream_module.py` | 假说生成 — H1-H6 策略池 |
| **MetaCognition** | `meta_cognition.py` | 仲裁层 — 学习权重的加权投票 |
| **MetaReasoningLayer** | `meta_reasoning.py` | 元推理 — 预测误差趋势监控 + 框架级反思 |
| **ReflectionEngine** | `reflection.py` | 反馈闭环 — 捕获纠正信号 + 会话自我评估 |
| **LanguageGenerator** | `language_generator.py` | 语言涌现 — 语料库学句式骨架 + 语气内容解耦 |
| **MotherController** | `mother_controller.py` | 主循环 — Semantic→Pragmatic→AI→MetaCognition→生成 |
| **CognitiveInterface** | `cognitive_interface.py` | 感官层 — 语言原语→结构假说→语用意图 |

## 快速开始

```bash
pip install ddgs
cd src
python asteriamind_web.py
# 浏览器打开 http://localhost:8866
```

**交互方式**: 教她事实 (猫是哺乳动物) / 问她问题 (企鹅是鸟类吗) / 纠正她 (不对，企鹅不是哺乳动物) / 她会自动搜索不确定的知识

**API 端点**: `POST /api/talk` (对话) | `GET /api/reflect` (自我评估 + 权重) | `GET /api/health` (系统健康)

## 模块定位表

| 模块 | 位置 | 一句话 |
|------|------|--------|
| CognitiveStarMap | 世界模型/认知空间 | 知识如何存储和关联 |
| MetaCognition | 仲裁 | 谁说得对听谁的，且从历史中学习该听谁的 |
| ActiveInference | 决定学什么 | "这条边不确定性 0.8，该验证了" |
| BudgetContest | 注意力分配 | 8 件事想学，先学收益最高的 2 件 |
| ActiveLearner | 获取信息 | KG没→星图没→搜网络→问用户 |
| MemoryConsolidation | 整理已知 | "猫和狗都是哺乳动物→提取模式" |
| DreamModule | 探索未知 | "企鹅迁徙关系为空，推测与海豹相似" |
| MetaReasoning | 反思框架 | "我怎么总是在鸟类分类上出错？" |
| ReflectionEngine | 反馈闭环 | "上一轮被纠正了，semantic 降权" |
| LanguageGenerator | 怎么说 | 从语料库学句式骨架，不是拼模板 |

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

