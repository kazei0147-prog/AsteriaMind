"""
WebSearch Bridge — 用 WebSearch 实时推数据到 HiveMind Portal

每次 poll 触发一次 WebSearch，解析搜索结果中的数值，
push 到 LiveSource。

适用于: 任何可搜索到的实时数值 (CO2, 温度, 股价, 空气质量指数等)
"""
import re
import sys
import threading
import time
sys.path.insert(0, "D:/AM/HiveMind_repo/src")

from AsteriaMind.portal import LiveSource, Portal, ConsoleSink, CuriosityEngine


class WebSearchFeeder:
    """
    从 WebSearch 结果中提取数值，推送到 LiveSource。

    用法:
        feeder = WebSearchFeeder("Mauna Loa CO2 latest weekly ppm", pattern=r"(\d+\.?\d*)\s*ppm")
        source = feeder.source  # LiveSource 实例
        feeder.start(interval=10)  # 每10秒搜索一次
    """

    def __init__(self, query: str, pattern: str = r"(\d+\.?\d*)\s*ppm"):
        self.query = query
        self.pattern = re.compile(pattern, re.IGNORECASE)
        self.source = LiveSource(max_buffer=100)
        self._running = False
        self._thread = None
        self.count = 0

    def _fetch_once(self) -> float | None:
        """执行一次搜索，提取数值"""
        try:
            # 这里需要运行在支持 WebSearch 的环境中
            # 在 bench 脚本中由外部调用 search_func
            pass
        except Exception:
            pass
        return None

    def start(self, interval: float = 10):
        """后台线程定时搜索推送"""
        self._running = True

        def _loop():
            while self._running:
                try:
                    val = self._fetch_once()
                    if val is not None:
                        self.source.push(val)
                        self.count += 1
                except Exception as e:
                    print(f"[Feeder] 搜索失败: {e}")
                time.sleep(interval)

        self._thread = threading.Thread(target=_loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False
        self.source.stop()
