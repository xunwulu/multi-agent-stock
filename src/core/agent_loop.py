"""
Agent Loop - 多智能体股票分析系统的核心循环

这是整个系统的心脏。一个 while 循环，不断调用 LLM、执行工具、直到模型说停。

参考: learn-claude-code s01_agent_loop.py (~80行)
哲学: 智能来自模型(GLM-5.1)，代码只提供环境(Harness)
"""

import json
import random
import threading
import time
import logging
from typing import Callable, Optional

import anthropic
import httpx

logger = logging.getLogger(__name__)

# 跨轮累积文字的总量上限（字符）：展示用"分析轨迹+成文"封顶，防 progress 文件膨胀。
# 超限时保留末尾（最接近结论的部分），开头标注已截断。
_ACCUM_TEXT_MAX = 20000


def _notify(on_event: Optional[Callable], payload: dict):
    """安全上报进度事件：无回调或回调异常都不影响主流程。"""
    if on_event is None:
        return
    try:
        on_event(payload)
    except Exception as e:  # pragma: no cover - 防御性
        logger.debug(f"[Agent Loop] on_event callback failed: {e}")


class TokenBucketRateLimiter:
    """Thread-safe token bucket for API call rate limiting."""

    def __init__(self, rate: float = 0.5, burst: int = 3):
        """
        Args:
            rate: average calls per second (0.5 = 1 call every 2s)
            burst: max calls allowed immediately
        """
        self.rate = rate
        self.burst = burst
        self._tokens = float(burst)
        self._last_refill = time.monotonic()
        self._lock = threading.Lock()

    def acquire(self):
        """Block until a token is available."""
        while True:
            with self._lock:
                now = time.monotonic()
                self._tokens = min(
                    self.burst,
                    self._tokens + (now - self._last_refill) * self.rate,
                )
                self._last_refill = now
                if self._tokens >= 1.0:
                    self._tokens -= 1.0
                    return
            time.sleep(0.1)


# Module-level rate limiter, shared across all AgentLoop instances
_global_rate_limiter: TokenBucketRateLimiter | None = None
_rate_limiter_lock = threading.Lock()


def _get_rate_limiter(config: dict) -> TokenBucketRateLimiter:
    global _global_rate_limiter
    if _global_rate_limiter is None:
        with _rate_limiter_lock:
            if _global_rate_limiter is None:
                rate = config.get("api_rate_limit", 0.5)
                burst = config.get("api_rate_burst", 3)
                _global_rate_limiter = TokenBucketRateLimiter(rate=rate, burst=burst)
                logger.info(
                    f"[Agent Loop] Rate limiter initialized: "
                    f"rate={rate}/s, burst={burst}"
                )
    return _global_rate_limiter


class AgentLoop:
    """Agent 核心循环"""

    # 可重试的异常类型
    # NotFoundError included: ZhipuAI proxy returns 404 under heavy load
    # (not a genuine "wrong URL" -- same endpoint works moments later)
    RETRYABLE_ERRORS = (
        anthropic.RateLimitError,
        anthropic.APIConnectionError,
        anthropic.APITimeoutError,
        anthropic.InternalServerError,
        anthropic.NotFoundError,
    )

    def __init__(self, config: dict):
        """
        初始化 Agent Loop

        Args:
            config: 模型配置，从 config/model.json 加载
                {
                    "api_key": "...",
                    "base_url": "https://open.bigmodel.cn/api/anthropic",
                    "model": "glm-5.1",
                    "max_tokens": 4096,
                    "max_iterations": 10,
                    "max_retries": 3,
                    "retry_base_delay": 2.0,
                    "api_rate_limit": 0.5,
                    "api_rate_burst": 3,
                    "request_timeout": 120
                }
        """
        self.config = config
        # Granular httpx timeouts: connect=10s kills TCP-handshake hangs (the
        # 9424s incident root cause); read/write/pool bound the other phases.
        # Scalar request_timeout is kept as the read fallback for old configs.
        _timeout = httpx.Timeout(
            connect=config.get("connect_timeout", 10),
            read=config.get("read_timeout", config.get("request_timeout", 120)),
            write=config.get("write_timeout", 30),
            pool=config.get("pool_timeout", 10),
        )
        self.client = anthropic.Anthropic(
            api_key=config["api_key"],
            base_url=config["base_url"],
            timeout=_timeout,
        )
        self.model = config["model"]
        self.max_tokens = config.get("max_tokens", 4096)
        self.max_iterations = config.get("max_iterations", 10)
        self.max_retries = config.get("max_retries", 3)
        self.retry_base_delay = config.get("retry_base_delay", 2.0)
        self.rate_limiter = _get_rate_limiter(config)
        self._first_call_succeeded = False

    def _call_with_retry(self, kwargs: dict, on_event: Optional[Callable] = None,
                         iteration: int = 0):
        """
        带指数退避的 API 调用

        对可恢复错误（限速、超时、连接失败、服务端错误）自动重试，
        对不可恢复错误（认证失败、请求格式错误）直接抛出。

        退避策略: delay = min(base * 2^attempt, 30s) + random jitter
        """
        for attempt in range(self.max_retries + 1):
            self.rate_limiter.acquire()
            try:
                response = self.client.messages.create(**kwargs)
                self._first_call_succeeded = True
                return response
            except anthropic.NotFoundError as e:
                # If never had a successful call, might be config error
                if not self._first_call_succeeded and attempt >= 1:
                    raise
                if attempt >= self.max_retries:
                    raise
                delay = min(
                    self.retry_base_delay * (2 ** attempt),
                    30.0,
                )
                jitter = delay * 0.1 * random.random()
                sleep_time = delay + jitter
                logger.warning(
                    f"[Agent Loop] NotFoundError (attempt {attempt + 1}/"
                    f"{self.max_retries}): {e}. "
                    f"Retrying in {sleep_time:.1f}s"
                )
                _notify(on_event, {
                    "kind": "retry", "iteration": iteration,
                    "retry_note": f"服务端繁忙(404)，{sleep_time:.0f}秒后自动重试",
                })
                time.sleep(sleep_time)
            except self.RETRYABLE_ERRORS as e:
                if attempt >= self.max_retries:
                    raise
                delay = min(
                    self.retry_base_delay * (2 ** attempt),
                    30.0,
                )
                jitter = delay * 0.1 * random.random()
                sleep_time = delay + jitter
                logger.warning(
                    f"[Agent Loop] Retryable error (attempt {attempt + 1}/"
                    f"{self.max_retries}): {type(e).__name__}: {e}. "
                    f"Retrying in {sleep_time:.1f}s"
                )
                _notify(on_event, {
                    "kind": "retry", "iteration": iteration,
                    "retry_note": f"API限流({type(e).__name__})，{sleep_time:.0f}秒后自动重试",
                })
                time.sleep(sleep_time)

    def run(
        self,
        system_prompt: str,
        messages: list[dict],
        tools: list[dict] | None = None,
        dispatch_map: dict[str, callable] | None = None,
        max_iterations: int | None = None,
        submit_tool_name: str | None = None,
        on_event: Optional[Callable] = None,
    ) -> dict:
        """
        运行 Agent 循环

        Args:
            system_prompt: 系统提示词（从 Skill 文件加载）
            messages: 对话历史 [{"role": "user", "content": "..."}]
            tools: 工具定义列表（Anthropic 格式）
            dispatch_map: 工具名 -> 处理函数 的映射
            max_iterations: 最大循环次数（覆盖默认值）
            submit_tool_name: 提交工具名（如 "submit_analysis"）。
                LLM 调用此工具时，捕获 input 作为 structured_output 并结束循环。
            on_event: 进度回调（可选）。收到原始进度 dict:
                {"kind": "iteration"|"tool"|"retry", ...}，
                由上层包装成契约事件（agent_heartbeat）。

        Returns:
            {
                "success": True/False,
                "content": "模型的最终文字回复",
                "structured_output": dict | None,
                "tool_calls": 3,
                "iterations": 4,
                "duration_ms": 5230,
                "error": None,
                "error_type": None | "api" | "max_iterations",
            }
        """
        max_iter = max_iterations or self.max_iterations
        start_time = time.time()
        total_tool_calls = 0

        # 跨轮累积的全部文字（展示用：分析轨迹 + 最终成文，不再只留末轮）
        all_text_parts: list[str] = []

        def _accumulated_text() -> str | None:
            """全部轮次文字拼接（轮间空行分隔，超限保尾）。"""
            txt = "\n\n".join(all_text_parts).strip()
            if not txt:
                return None
            if len(txt) > _ACCUM_TEXT_MAX:
                txt = "(前文已截断)\n\n" + txt[-_ACCUM_TEXT_MAX:]
            return txt

        # 可观测性: 记录每轮 token 用量
        token_log = []
        total_input = 0
        total_output = 0
        truncated = False

        # 如果没有工具，传 None（API 不接受空列表）
        api_tools = tools if tools else None

        for i in range(max_iter):
            iteration = i + 1
            logger.info(f"[Agent Loop] Iteration {iteration}/{max_iter}")
            _notify(on_event, {
                "kind": "iteration", "iteration": iteration,
                "max_iterations": max_iter,
                "elapsed_ms": int((time.time() - start_time) * 1000),
            })

            try:
                kwargs = {
                    "model": self.model,
                    "max_tokens": self.max_tokens,
                    "system": system_prompt,
                    "messages": messages,
                }
                if api_tools:
                    kwargs["tools"] = api_tools

                response = self._call_with_retry(
                    kwargs, on_event=on_event, iteration=iteration
                )

            except Exception as e:
                logger.error(f"[Agent Loop] API error (retries exhausted): {e}")
                return {
                    "success": False,
                    "content": _accumulated_text(),
                    "last_round_text": None,
                    "structured_output": None,
                    "tool_calls": total_tool_calls,
                    "iterations": iteration,
                    "duration_ms": int((time.time() - start_time) * 1000),
                    "error": f"API error: {e}",
                    "error_type": "api",
                    "token_usage": {
                        "total_input": total_input,
                        "total_output": total_output,
                        "total_tokens": total_input + total_output,
                        "truncated": truncated,
                        "per_iteration": token_log,
                    },
                }

            # 处理响应
            stop_reason = response.stop_reason
            logger.info(f"[Agent Loop] Stop reason: {stop_reason}")

            usage = getattr(response, "usage", None)
            input_t = getattr(usage, "input_tokens", 0) or 0
            output_t = getattr(usage, "output_tokens", 0) or 0
            total_input += input_t
            total_output += output_t
            token_log.append({
                "iteration": iteration,
                "input_tokens": input_t,
                "output_tokens": output_t,
                "stop_reason": stop_reason,
            })
            logger.info(
                f"[Agent Loop] Token usage: "
                f"input={input_t}, output={output_t}, "
                f"stop={stop_reason}"
            )
            if stop_reason == "max_tokens":
                truncated = True
                logger.warning(
                    f"[Agent Loop] Output truncated! "
                    f"max_tokens={self.max_tokens} too small."
                )

            text_parts = []
            tool_uses = []

            for block in response.content:
                if block.type == "text":
                    text_parts.append(block.text)
                elif block.type == "tool_use":
                    tool_uses.append(block)

            # 跨轮累积：本轮有文字则并入轨迹（展示用），不再丢弃
            if text_parts:
                all_text_parts.append("\n".join(text_parts))

            if stop_reason != "tool_use" or not tool_uses:
                duration_ms = int((time.time() - start_time) * 1000)
                final_text = "\n".join(text_parts)
                logger.info(
                    f"[Agent Loop] Done. {iteration} iterations, "
                    f"{total_tool_calls} tool calls, {duration_ms}ms"
                )
                return {
                    "success": True,
                    "content": _accumulated_text(),
                    "last_round_text": final_text if final_text else None,
                    "structured_output": None,
                    "tool_calls": total_tool_calls,
                    "iterations": iteration,
                    "duration_ms": duration_ms,
                    "error": None,
                    "error_type": None,
                    "token_usage": {
                        "total_input": total_input,
                        "total_output": total_output,
                        "total_tokens": total_input + total_output,
                        "truncated": truncated,
                        "per_iteration": token_log,
                    },
                }

            messages.append({"role": "assistant", "content": response.content})

            if submit_tool_name:
                for tu in tool_uses:
                    if tu.name == submit_tool_name:
                        logger.info(
                            f"[Agent Loop] Submit tool called: {tu.name}, "
                            f"fields={list(tu.input.keys())[:10]}"
                        )
                        duration_ms = int((time.time() - start_time) * 1000)
                        _last_rt = "\n".join(text_parts)
                        return {
                            "success": True,
                            "content": _accumulated_text(),
                            "last_round_text": _last_rt if _last_rt else None,
                            "structured_output": tu.input,
                            "tool_calls": total_tool_calls + 1,
                            "iterations": iteration,
                            "duration_ms": duration_ms,
                            "error": None,
                            "error_type": None,
                            "token_usage": {
                                "total_input": total_input,
                                "total_output": total_output,
                                "total_tokens": total_input + total_output,
                                "truncated": truncated,
                                "per_iteration": token_log,
                            },
                        }

            tool_results = []
            for tu in tool_uses:
                tool_name = tu.name
                tool_input = tu.input
                tool_id = tu.id
                total_tool_calls += 1

                logger.info(
                    f"[Agent Loop] Tool call #{total_tool_calls}: "
                    f"{tool_name}({json.dumps(tool_input, ensure_ascii=False)})"
                )

                if dispatch_map and tool_name in dispatch_map:
                    try:
                        _t0 = time.time()
                        result = dispatch_map[tool_name](**tool_input)
                        _tool_ms = int((time.time() - _t0) * 1000)
                        _notify(on_event, {
                            "kind": "tool", "iteration": iteration,
                            "max_iterations": max_iter, "tool": tool_name,
                            "tool_status": "ok", "duration_ms": _tool_ms,
                            "elapsed_ms": int((time.time() - start_time) * 1000),
                        })

                        try:
                            from src.infra.quality import validate_tool_output
                            result = validate_tool_output(tool_name, result)
                        except Exception as qe:
                            logger.debug(
                                f"[Agent Loop] Quality check skipped: {qe}"
                            )

                        result_str = json.dumps(
                            result, ensure_ascii=False, default=str
                        )
                        logger.info(
                            f"[Agent Loop] Tool result: "
                            f"{result_str[:200]}..."
                            if len(result_str) > 200
                            else f"[Agent Loop] Tool result: {result_str}"
                        )
                    except Exception as e:
                        result_str = json.dumps(
                            {"error": str(e)}, ensure_ascii=False
                        )
                        logger.error(f"[Agent Loop] Tool error: {e}")
                else:
                    result_str = json.dumps(
                        {"error": f"Unknown tool: {tool_name}"},
                        ensure_ascii=False,
                    )
                    logger.error(f"[Agent Loop] Unknown tool: {tool_name}")

                tool_results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": tool_id,
                        "content": result_str,
                    }
                )

            messages.append({"role": "user", "content": tool_results})

        duration_ms = int((time.time() - start_time) * 1000)
        logger.warning(
            f"[Agent Loop] Max iterations ({max_iter}) reached. "
            f"{total_tool_calls} tool calls, {duration_ms}ms"
        )
        return {
            "success": False,
            "content": _accumulated_text(),
            "last_round_text": "\n".join(text_parts) if text_parts else None,
            "structured_output": None,
            "tool_calls": total_tool_calls,
            "iterations": max_iter,
            "duration_ms": duration_ms,
            "error": f"Max iterations ({max_iter}) reached",
            "error_type": "max_iterations",
            "token_usage": {
                "total_input": total_input,
                "total_output": total_output,
                "total_tokens": total_input + total_output,
                "truncated": truncated,
                "per_iteration": token_log,
            },
        }
