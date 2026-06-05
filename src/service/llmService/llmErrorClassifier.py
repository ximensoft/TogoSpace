from constants import LlmErrorCategory

from litellm.exceptions import (
    APIConnectionError,
    AuthenticationError,
    BadRequestError,
    ContentPolicyViolationError,
    ContextWindowExceededError,
    InternalServerError,
    InvalidRequestError,
    PermissionDeniedError,
    RateLimitError,
    ServiceUnavailableError,
    Timeout,
)

# 上下文超长关键词（部分 provider 不抛 ContextWindowExceededError，只返回文本）
_CONTEXT_WINDOW_KEYWORDS = (
    "context_length_exceeded",
    "maximum context length",
    "prompt is too long",
    "input is too long",
    "input too long",
    "exceeds the context window",
    "too many tokens",
    "context window",
    "max_tokens",
    "token limit",
)

# 可重试的错误分类
RETRYABLE_CATEGORIES = {
    LlmErrorCategory.RATE_LIMITED,
    LlmErrorCategory.SERVER_ERROR,
    LlmErrorCategory.NETWORK_ERROR,
    LlmErrorCategory.UNKNOWN,
}


def classify_llm_error(error: Exception) -> LlmErrorCategory:
    """将 LLM 调用异常分类为 LlmErrorCategory 枚举值。"""
    if isinstance(error, ContextWindowExceededError):
        return LlmErrorCategory.CONTEXT_WINDOW

    if isinstance(error, (AuthenticationError, PermissionDeniedError)):
        return LlmErrorCategory.AUTH_ERROR

    if isinstance(error, ContentPolicyViolationError):
        return LlmErrorCategory.CONTENT_POLICY

    if isinstance(error, RateLimitError):
        return LlmErrorCategory.RATE_LIMITED

    if isinstance(error, (InternalServerError, ServiceUnavailableError)):
        return LlmErrorCategory.SERVER_ERROR

    if isinstance(error, (APIConnectionError, Timeout)):
        return LlmErrorCategory.NETWORK_ERROR

    if isinstance(error, (BadRequestError, InvalidRequestError)):
        error_text = str(error).lower()
        if any(kw in error_text for kw in _CONTEXT_WINDOW_KEYWORDS):
            return LlmErrorCategory.CONTEXT_WINDOW
        return LlmErrorCategory.INVALID_REQUEST

    # 兜底：关键词匹配上下文超长
    error_text = str(error).lower()
    if any(kw in error_text for kw in _CONTEXT_WINDOW_KEYWORDS):
        return LlmErrorCategory.CONTEXT_WINDOW

    return LlmErrorCategory.UNKNOWN
