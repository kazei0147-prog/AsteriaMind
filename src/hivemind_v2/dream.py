"""
梦境引擎 - HiveMind 2.0 的记忆与休眠

v2.0 版的梦境比 v0.6 更简洁:
- 不是训练 mini 模型，而是直接保存/加载学习器状态
- 每个学习器的 μ/σ/α/track_record → JSON 文件
- 下次冷启动直接加载，跳过预热期
- 同时支持"跨数据集迁移"——在一个数据集上学到的信念应用到另一个
"""

import json
import logging
from pathlib import Path
from typing import List, Optional
from .learner import Learner

logger = logging.getLogger("hivemind_v2.dream")


class DreamStore:
    """梦境记忆库——学习器的长期记忆"""

    def __init__(self, filepath: Optional[str] = None):
        self.filepath = filepath

    def save(self, learners: List[Learner], filepath: Optional[str] = None) -> dict:
        """保存所有学习器状态到文件"""
        path = filepath or self.filepath
        if not path:
            raise ValueError("需要指定保存路径")

        state = {
            "version": "2.0",
            "n_learners": len(learners),
            "learners": [l.export_state() for l in learners],
        }

        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2, ensure_ascii=False)

        logger.info(f"梦境保存: {len(learners)} 个学习器 → {path} ({len(json.dumps(state))} bytes)")
        return state

    def load(self, filepath: Optional[str] = None) -> List[dict]:
        """从文件加载学习器状态（不创建新对象，只返回 dict）"""
        path = filepath or self.filepath
        if not path:
            raise ValueError("需要指定加载路径")

        with open(path, "r", encoding="utf-8") as f:
            state = json.load(f)

        logger.info(f"梦境加载: {state.get('n_learners')} 个学习器 ← {path}")
        return state["learners"]

    @staticmethod
    def restore_learners(states: List[dict], base_window_size: int = 10) -> List[Learner]:
        """从状态字典列表恢复学习器对象"""
        return [Learner.from_state(s) for s in states]
