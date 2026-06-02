# -*- coding: utf-8 -*-
"""
AI 客户端模块 — 统一的 AI API 调用 + 熔断 + 重试

特性:
  - 支持 DeepSeek / 硅基流动 / OpenAI / Ollama
  - 自动绕过系统代理（避免本地代理未启动导致失败）
  - 指数退避重试（最多 3 次）
  - 熔断保护：连续 5 次失败后暂停 30 秒
  - 结构化的错误日志
"""

import time
import logging
from typing import Optional

import requests

logger = logging.getLogger("AIClient")


class CircuitBreaker:
    """简单的熔断器"""

    def __init__(self, failure_threshold: int = 5, cooldown_seconds: float = 30.0):
        self.failure_threshold = failure_threshold
        self.cooldown_seconds = cooldown_seconds
        self._failure_count = 0
        self._last_failure_time = 0.0
        self._state = "CLOSED"  # CLOSED | OPEN | HALF_OPEN

    @property
    def state(self) -> str:
        return self._state

    def record_success(self):
        if self._state == "HALF_OPEN":
            logger.info("熔断器: HALF_OPEN → CLOSED (探测成功)")
        self._failure_count = 0
        self._state = "CLOSED"

    def record_failure(self):
        self._failure_count += 1
        self._last_failure_time = time.time()
        if self._state == "HALF_OPEN":
            logger.warning("熔断器: HALF_OPEN → OPEN (探测失败)")
            self._state = "OPEN"
        elif self._failure_count >= self.failure_threshold:
            logger.warning(f"熔断器: CLOSED → OPEN (连续 {self._failure_count} 次失败)")
            self._state = "OPEN"

    def allow_request(self) -> bool:
        if self._state == "CLOSED":
            return True
        if self._state == "OPEN":
            if time.time() - self._last_failure_time >= self.cooldown_seconds:
                logger.info("熔断器: OPEN → HALF_OPEN (冷却到期，允许探测)")
                self._state = "HALF_OPEN"
                return True
            return False
        return True  # HALF_OPEN


class AIClient:
    """统一的 AI API 客户端，自带重试和熔断"""

    def __init__(self, api_key: str, base_url: str, model: str,
                 system_prompt: str = "",
                 max_tokens: int = 200, temperature: float = 0.85,
                 max_retries: int = 3, timeout: float = 15.0):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.system_prompt = system_prompt
        self.max_tokens = max_tokens
        self.temperature = temperature
        self.max_retries = max_retries
        self.timeout = timeout
        self.breaker = CircuitBreaker()

    @property
    def available(self) -> bool:
        return bool(self.base_url and self.model and self.api_key
                    and "sk-your-" not in self.api_key
                    and self.breaker.allow_request())

    def chat(self, user_message: str) -> Optional[str]:
        """调用 AI 生成回复（带重试和熔断）"""
        if not self.api_key or "sk-your-" in self.api_key:
            logger.warning("AI API Key 未配置（仍是默认值）")
            return None

        if not self.breaker.allow_request():
            logger.warning("熔断器开路，跳过本次 AI 请求")
            return None

        last_error = None
        for attempt in range(1, self.max_retries + 1):
            try:
                resp = requests.post(
                    f"{self.base_url}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": self.model,
                        "messages": [
                            {"role": "system", "content": self.system_prompt},
                            {"role": "user", "content": user_message},
                        ],
                        "max_tokens": self.max_tokens,
                        "temperature": self.temperature,
                    },
                    timeout=self.timeout,
                    # 绕过系统代理，避免本地代理未启动导致请求全部失败
                    proxies={"http": "", "https": ""},
                )
                if resp.status_code == 200:
                    data = resp.json()
                    result = data["choices"][0]["message"]["content"].strip()
                    self.breaker.record_success()
                    return result
                else:
                    last_error = f"HTTP {resp.status_code}: {resp.text[:200]}"
            except requests.exceptions.Timeout:
                last_error = "请求超时"
            except requests.exceptions.ConnectionError as e:
                last_error = f"连接错误: {e}"
            except Exception as e:
                last_error = f"未预期错误: {e}"

            if attempt < self.max_retries:
                wait = 2 ** attempt  # 指数退避: 2s, 4s, 8s
                logger.warning(f"AI 请求失败 (第{attempt}/{self.max_retries}次): {last_error}，{wait}s 后重试")
                time.sleep(wait)

        # 所有重试耗尽
        logger.error(f"AI 请求彻底失败 (已重试{self.max_retries}次): {last_error}")
        self.breaker.record_failure()
        return None


def create_ai_client_from_config() -> Optional[AIClient]:
    """从 config.py 创建 AIClient 实例"""
    from config import (
        ENABLE_AI_REPLY, AI_PROVIDER,
        DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL, DEEPSEEK_MODEL,
        SILICONFLOW_API_KEY, SILICONFLOW_BASE_URL, SILICONFLOW_MODEL,
        OPENAI_API_KEY, OPENAI_BASE_URL, OPENAI_MODEL,
        OLLAMA_BASE_URL, OLLAMA_MODEL, AI_SYSTEM_PROMPT,
    )

    if not ENABLE_AI_REPLY:
        return None

    provider = AI_PROVIDER.lower()
    providers = {
        "deepseek": (DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL, DEEPSEEK_MODEL),
        "siliconflow": (SILICONFLOW_API_KEY, SILICONFLOW_BASE_URL, SILICONFLOW_MODEL),
        "openai": (OPENAI_API_KEY, OPENAI_BASE_URL, OPENAI_MODEL),
        "ollama": (OLLAMA_BASE_URL + "x", OLLAMA_BASE_URL, OLLAMA_MODEL),  # key=any, ollama 不需要
    }

    if provider not in providers:
        logger.error(f"未知的 AI 提供商: {provider}")
        return None

    api_key, base_url, model = providers[provider]
    return AIClient(
        api_key=api_key,
        base_url=base_url,
        model=model,
        system_prompt=AI_SYSTEM_PROMPT,
    )
