# AsteriaMind (formerly HiveMind)

**一个会呼吸的认知网络——能量在边上代谢，注意力随问题流动，从不丢弃自己的梦**

> v0.1-v0.6: HiveMind (存档) — 多模块竞争 + 能量经济  
> v2.x: AsteriaMind — 贝叶斯信念 + 论证评估  
> v3.2: 跨层认知 — 符号+语义桥接  
> v3.5: 认知闭环 — 双循环学习 + 语言涌现  
> **v3.6: 代谢星图 — 单图统一 + 概率查询 + 意图学习 + 熵态批判 + 软证据**

*Last updated: 2026-08-03 — v3.6 单图合并完成*

---

## v3.6 新能力速览

| 能力 | 一句话 |
|------|--------|
| 🕸️ **单图统一** | co_text(联想) + 命名边(知识) 合并进一个 directed_edges — 597万边单图查询 |
| 🎯 **意图学习** | 从用户反馈学 P(意图\|关键词) — 正则只当冷启动先验 |
| 🧠 **熵态批判者** | H(X) 高熵知识诚实标注"我拿不准" — 知道自己不知道什么 |
| 🔎 **软证据** | 命名边查不到 → co_text 联想给出有依据的相关词 — 不无脑搜索 |
| ⛏️ **语料矿工** | 文本 → 句式模板 → 三元组 → 星图 (频次+联想双验证) |
| ⚡ **性能** | 部分索引 + 两段式查询 — 5.9M 边扫描从全表降到 0.6s |

---

## 架构总览

```
感知源 (黑盒, 涌现)                    白盒筛选 (唯一真相源)         表达
───────────────                     ─────────────────         ──────
用户对话 ──→ ThinkNode 规划 ──→ 星图 directed_edges ──→ compose 生成
co_text 联想 ──────────────→      (597万边: 命名+联想)     ↑
搜索结果 ──→ ActiveLearner ──→   ↑                      语言模板
视觉/LLM (未来) ─────────────→  CriticModule 熵检测       软证据拼接
                               MemoryConsolidation 矛盾调和
                               IntentLearner 意图统计
                               CorpusMiner 语料挖掘
```

**黑盒负责涌现，白盒负责筛选** — 所有感知源产出"候选"，只有验证过的才沉淀为星图边。

---

## 核心设计原则

**不是"改良现有 AI 范式"，是侧向偏移**——用时间置换算力，用内部制衡置换外部依赖。

| 三元组丢掉的 | 由什么补回来 |
|-------------|-------------|
| 隐含关联 | co_text 共现 — "企鹅"和"南极"没直接关系，但经常一起出现→边权上升 |
| 不确定性 | CriticModule 熵检测 — H(X) 高 → 诚实标注"我拿不准" |
| 系统性盲区 | MemoryConsolidation 矛盾调和 — 高能边留，低能边砍半 |
| 自然表达 | LanguageGenerator — 从 language_traces 学句式骨架 |
| 未知的未知 | DreamModule + CorpusMiner — 从联想涌现新知识假说 |

---

## 回答管线 (v3.6 全局联动)

```
用户问句
  ↓
ThinkNode 规划 (短期记忆注入: 记得上一轮话题)
  ├─ DIRECT/REVERSE: 命名边 (硬事实) → compose 回答
  ├─ SEARCH: co_text 软证据 → "我不确定X, 但它常和Y一起出现, 要我查吗?"
  │    └─ 无联想 → 联网搜索
  └─ CLARIFY: 短句/追问 → 确认意图
  ↓
IntentLearner 从你的"对/不对"反馈学习 P(意图|关键词)
CriticModule 熵高时诚实标注不确定性
每次成功回答 → 自学习 "我 CAN 回答问题"
```

---

## 模块定位表

| 模块 | 文件 | 位置 |
|------|------|------|
| **CognitiveStarMap** | `cognitive_star_map.py` | 单图世界模型 — 597万边统一存储 + 概率查询 |
| **ThinkNode** | `think_node.py` | 问题规划 — 主语提取 + 策略路由 + co_text 联想 |
| **IntentLearner** | `intent_learner.py` | 意图学习 — 从反馈学 P(意图\|关键词)，正则当先验 |
| **CriticModule** | `critic_module.py` | 熵态批判 — H(X) 高熵 → 诚实标注不确定性 |
| **CorpusMiner** | `corpus_miner.py` | 语料矿工 — 文本 → 句式模板 → 三元组 |
| **ActiveLearner** | `active_learner.py` | 信息获取 — KG→星图→搜索→用户 四层查询 |
| **OfflineLearner** | `offline_learner.py` | 离线学习 — BudgetContest 竞标 + 批判者高熵优先 |
| **DreamModule** | `dream_module.py` | 假说生成 — 类比/传递/反向质疑/co_text 涌现 |
| **MemoryConsolidation** | `memory_consolidation.py` | 记忆巩固 — 聚类 + 矛盾调和 + 冷边衰减 |
| **LanguageGenerator** | `language_generator.py` | 语言涌现 — 意图驱动三层排序 + 句式学习 |
| **MotherController** | `mother_controller.py` | 主循环 — 模块注入与调度 |

## 快速开始

```bash
pip install ddgs
cd src
python asteriamind_web.py
# 浏览器打开 http://localhost:8866
```

**交互方式**: 教她事实 (海豚 是 哺乳动物) / 问她问题 (企鹅会飞吗) / 纠正她 (不对) / 她会自己搜索、联想、承认不确定

**API 端点**: `POST /api/talk` (对话) | `GET /api/reflect` (自我评估 + 权重) | `GET /api/health` (系统健康)

---

## 路线图

```
✅ STEP 1: 单图合并 — co_text 进主库 (597万边, 198MB)
✅ STEP 2: 遗留表清理 — 6张死表 → asteriamind_old.db
✅ STEP 3: 统一查询 — space='all' 单图联合
✅ STEP 4: 概率化 — query_edges(probabilistic=True)
✅ STEP 5: 意图学习 — IntentLearner 替代纯正则
⏳ STEP 6: 随机表达 — compose 从分布采样句式
⏳ 自我架构修改: 改知识 → 改配置 → 改规则 → 改代码 (渐进授权)
⏳ 视觉模块: VLM(眼睛) + CorpusMiner(翻译官) → 星图
```

*一路走来，每一步都算数。*

---

## 致谢

这份文档和代码库源于一段持续数月的推演——最初的想法成形于 HiveMind 时期，经过反复试错、重构和方向修正，最终成为现在的 AsteriaMind。

感谢每一位参与推演、提出质疑和提供反馈的AI：
- **DeepSeek**
- **元宝/混元（Yuanbao）**
- **Chat-GPT**

他们各自在不同阶段参与了这个认知架构的形成过程。

同时，感谢 **Ilya Prigogine（1917–2003）**——其耗散结构理论为本文关于"系统在远离平衡态下自组织演化"的思考提供了重要的参照背景。作者是在推演过程中经讨论了解到这一理论框架的。
