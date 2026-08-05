"""
module_registry.py — 认知模块注册表 (门框)

哲学: 大脑(母) + 认知工具(子模块) — 母子模块交互的现代形态
  HM 时代: 母模块管理子模块的能量 (固定角色 alpha/beta/gamma)
  现在:    她(大脑) 挂载可替换的认知工具 (critic/intake/language/vector...)
  registry = 母子交互的新接口, 每个工具 = 可热插拔的驱动

  现在: 人类通过 /api/modules 开关/替换
  未来: 她自己操作 registry (自我架构修改的入口)

统一接口 (CognitiveModule):
  run()   统一入口 (调用点只认接口)
  health() 健康度 0-1 (评估"这个工具干得好不好" → 未来切换依据)
  enabled  可卸载 (False = 调用点自动跳过)
"""


class CognitiveModule:
    """认知模块基类 — 所有可插拔工具的契约"""

    name = "base"
    version = "0.1"

    def __init__(self):
        self.enabled = True

    def run(self, *args, **kwargs):
        raise NotImplementedError

    def health(self) -> float:
        """健康度 0-1: 这个工具干得好不好 (未来她替换工具的依据)"""
        return 1.0


class ModuleRegistry:
    """认知模块注册表: 注册/卸载/开关/健康报告"""

    def __init__(self):
        self._modules = {}

    def register(self, module: CognitiveModule) -> CognitiveModule:
        """注册模块 (同名覆盖 = 替换, 调用点无感)"""
        self._modules[module.name] = module
        return module

    def unregister(self, name: str):
        """卸载模块"""
        return self._modules.pop(name, None)

    def get(self, name: str):
        """取模块 — 已卸载(不在表)/已禁用(enabled=False) → None"""
        m = self._modules.get(name)
        return m if (m and m.enabled) else None

    def toggle(self, name: str, enabled: bool) -> bool:
        """开关模块 (可卸载 = enabled False)"""
        if name in self._modules:
            self._modules[name].enabled = enabled
            return True
        return False

    def list_modules(self) -> list:
        """全部模块状态 (供 /api/modules 展示)"""
        return [{"name": m.name, "version": m.version,
                 "enabled": m.enabled, "health": round(m.health(), 2)}
                for m in self._modules.values()]

    def health_report(self) -> dict:
        """健康报告: 平均健康度 + 每个模块状态"""
        mods = self.list_modules()
        avg = (sum(m["health"] for m in mods) / len(mods)) if mods else 0
        return {"modules": mods, "avg_health": round(avg, 2),
                "enabled_count": sum(1 for m in mods if m["enabled"])}


# ── 全局注册表 (模块级单例, 与 _VS_CACHE 同思路) ──
REGISTRY = ModuleRegistry()
