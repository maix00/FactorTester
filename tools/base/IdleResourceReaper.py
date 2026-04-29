"""
空闲资源回收线程

依赖 ResourceRegistry 接口，定期扫描闲置超时的资源并执行回收回调。
registry 可以是 LocalResourceRegistry（单机）或 RedisResourceRegistry（分布式），
Reaper 本身不需要任何改动。
"""
import logging
import threading
from typing import Callable

from tools.base.ResourceRegistry import ResourceRegistry

logger = logging.getLogger(__name__)


class IdleResourceReaper:
    """
    空闲资源回收器。

    registry:     资源注册表（记录最后使用时间）
    idle_timeout: 闲置超时秒数
    interval:     扫描间隔秒数
    on_recycle:   回收回调 f(resource_id) → None，由业务注册
    """

    def __init__(
        self,
        registry: ResourceRegistry,
        idle_timeout: float = 60,
        interval: float = 5,
        on_recycle: Callable[[str], None] | None = None,
    ):
        self.registry = registry
        self.idle_timeout = idle_timeout
        self.interval = interval
        self._on_recycle = on_recycle
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    @property
    def on_recycle(self) -> Callable[[str], None] | None:
        return self._on_recycle

    @on_recycle.setter
    def on_recycle(self, fn: Callable[[str], None] | None):
        self._on_recycle = fn

    def start(self):
        """启动守护线程。"""
        if self._thread is not None:
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, daemon=True, name="idle-resource-reaper")
        self._thread.start()

    def stop(self):
        """停止守护线程。"""
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=10)
            self._thread = None

    def _run(self):
        while not self._stop_event.wait(self.interval):
            try:
                idle_ids = self.registry.get_idle_resources(self.idle_timeout)
                for rid in idle_ids:
                    if self._on_recycle:
                        try:
                            self._on_recycle(rid)
                        except Exception:
                            logger.exception("Error recycling resource: %s", rid)
                    self.registry.remove(rid)
            except Exception:
                logger.exception("Error during idle resource scan")
