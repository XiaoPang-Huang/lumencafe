"""进程内限流（PRD N14）：同 IP 分钟级滑动窗口。

两人场景无 Redis 依赖；未来上多进程时在此换实现，接口不变。
"""
import time
from collections import defaultdict, deque

_buckets: dict[str, deque[float]] = defaultdict(deque)


def hit(key: str, limit: int, window_sec: float = 60.0) -> bool:
    """计数一次；超出 limit 返回 False。key 例：``login:192.168.1.1``。"""
    now = time.monotonic()
    q = _buckets[key]
    while q and now - q[0] > window_sec:
        q.popleft()
    if len(q) >= limit:
        return False
    q.append(now)
    return True
