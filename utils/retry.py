"""
utils/retry.py
==============
指数退避重试 + 降级逻辑

用法:
  from utils.retry import fetch_with_retry, FallbackChain
  
  # 最简单：自动重试3次
  data = fetch_with_retry(lambda: requests.get(url).json())
  
  # 降级链：新浪 → 腾讯 → Yahoo
  chain = FallbackChain([
      (fetch_sina, {}),
      (fetch_tencent, {}),
      (fetch_yahoo, {}),
  ])
  data = chain.execute()
"""

import time
import logging
import functools
from typing import Callable, Any, Tuple, Optional, List
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class RetryResult:
    """重试结果"""
    success: bool
    value: Any = None
    error: str = ""
    attempts: int = 0
    source: str = ""


def fetch_with_retry(
    fn: Callable[[], Any],
    max_attempts: int = 3,
    initial_delay: float = 0.5,
    backoff_factor: float = 2.0,
    exceptions: Tuple = (Exception,),
    on_retry: Optional[Callable[[int, str], None]] = None,
) -> RetryResult:
    """
    指数退避重试装饰器/函数
    
    Args:
        fn: 要执行的函数（无参数）
        max_attempts: 最大尝试次数
        initial_delay: 初始延迟（秒）
        backoff_factor: 退避系数
        exceptions: 需要重试的异常类型
        on_retry: 重试时的回调 (attempt, error_msg)
    
    Returns:
        RetryResult对象
    """
    last_error = ""
    
    for attempt in range(1, max_attempts + 1):
        try:
            value = fn()
            return RetryResult(success=True, value=value, attempts=attempt)
        except exceptions as e:
            last_error = str(e)
            if attempt == max_attempts:
                break
            
            delay = initial_delay * (backoff_factor ** (attempt - 1))
            logger.warning(f"[Retry] attempt {attempt}/{max_attempts} failed: {last_error}, "
                          f"retrying in {delay:.1f}s...")
            
            if on_retry:
                on_retry(attempt, last_error)
            
            time.sleep(delay)
    
    return RetryResult(success=False, error=last_error, attempts=max_attempts)


def retry(max_attempts: int = 3, initial_delay: float = 0.5, backoff: float = 2.0):
    """
    装饰器形式的重试
    
    用法:
        @retry(max_attempts=3)
        def fetch_data():
            return requests.get(url).json()
    """
    def decorator(fn: Callable) -> Callable:
        @functools.wraps(fn)
        def wrapper(*args, **kwargs) -> Any:
            def call():
                return fn(*args, **kwargs)
            result = fetch_with_retry(
                call,
                max_attempts=max_attempts,
                initial_delay=initial_delay,
                backoff_factor=backoff,
            )
            if result.success:
                return result.value
            else:
                raise result.error and Exception(result.error)
        return wrapper
    return decorator


class FallbackChain:
    """
    降级链：尝试多个数据源，按优先级排序
    
    用法:
        chain = FallbackChain([
            (fetch_sina_etf, {"symbol": "510300"}),
            (fetch_tencent_etf, {"symbol": "510300"}),
            (fetch_yahoo_etf, {"symbol": "510300.SS"}),
        ])
        df = chain.execute()
    """
    
    def __init__(
        self,
        sources: List[Tuple[Callable, dict]],
        timeout: float = 10.0,
    ):
        """
        Args:
            sources: [(fn, kwargs), ...] 元组列表，按优先级排序
            timeout: 单个数据源超时（秒）
        """
        self.sources = sources
        self.timeout = timeout
    
    def execute(self) -> Any:
        """执行降级链，返回第一个成功的结果"""
        last_error = ""
        
        for i, (fn, kwargs) in enumerate(self.sources):
            source_name = fn.__name__
            
            def call():
                return fn(**kwargs)
            
            result = fetch_with_retry(
                call,
                max_attempts=3,
                initial_delay=0.5,
                backoff_factor=2.0,
                on_retry=lambda a, e: logger.warning(f"  [{source_name}] retry {a}: {e[:50]}"),
            )
            
            if result.success:
                logger.info(f"[FallbackChain] ✓ {source_name} succeeded (attempts={result.attempts})")
                result.source = source_name
                return result
            
            last_error = result.error
            logger.warning(f"[FallbackChain] ✗ {source_name} failed: {last_error[:80]}")
        
        # 全部失败
        logger.error(f"[FallbackChain] All {len(self.sources)} sources failed. Last error: {last_error}")
        raise RuntimeError(f"所有数据源均失败: {last_error}")
    
    def execute_safe(self, default=None) -> Any:
        """安全版本：全部失败时返回default"""
        try:
            return self.execute()
        except Exception:
            return default


# ============ 专门给 fetcher.py 用的curl封装 ============

import subprocess


def curl_with_retry(
    url: str,
    headers: dict = None,
    max_attempts: int = 3,
    timeout: int = 15,
) -> str:
    """
    带重试的curl请求
    
    Returns:
        response body (str)
    Raises:
        RuntimeError if all attempts fail
    """
    def call():
        cmd = ["curl", "-s", "--noproxy", "*", "-L", "--max-time", str(timeout)]
        if headers:
            for k, v in headers.items():
                cmd += ["-H", f"{k}: {v}"]
        cmd.append(url)
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout + 5)
        return result.stdout.strip()
    
    result = fetch_with_retry(
        call,
        max_attempts=max_attempts,
        initial_delay=1.0,
        backoff_factor=2.0,
        on_retry=lambda a, e: logger.warning(f"[curl retry] {a}: {e[:60]}"),
    )
    
    if result.success:
        return result.value
    raise RuntimeError(f"curl failed after {result.attempts} attempts: {result.error}")
