"""통일된 에러/응답 포맷.

korean-law-mcp 패턴 이식: 결과 없음/에러를 LLM이 기계적으로 감지하도록
[NOT_FOUND]/[ERROR] 프리픽스를 붙이고, "추측하지 말고 실패를 보고하라"를 명시한다.
(환각 방지)
"""

import re

# 에러 코드
NOT_FOUND = "NOT_FOUND"
INVALID_PARAM = "INVALID_PARAMETER"
API_ERROR = "EXTERNAL_API_ERROR"
NO_KEY = "NO_SERVICE_KEY"


class ArchHubError(Exception):
    """건축HUB 도구 에러. code/suggestions를 담아 포맷팅한다."""

    def __init__(self, message: str, code: str = API_ERROR, suggestions=None):
        super().__init__(message)
        self.code = code
        self.suggestions = suggestions or []


def mask_key(text: str) -> str:
    """에러 메시지/URL에 노출될 수 있는 서비스키를 마스킹."""
    if not text:
        return text
    # ?serviceKey=... / &ServiceKey=... 형태
    text = re.sub(r"([?&](?:serviceKey|ServiceKey|key)=)[^&\s]+", r"\1***", text)
    return text


def not_found(message: str, suggestions=None) -> str:
    """데이터 없음 응답. LLM이 임의로 답을 만들지 않도록 경고를 포함한다."""
    lines = [f"[{NOT_FOUND}] {message}", ""]
    lines.append(
        "⚠️ 이 도구는 요청한 데이터를 찾지 못했습니다. "
        "추측하거나 지어내지 말고, 사용자에게 '해당 데이터 없음'을 명시하세요."
    )
    if suggestions:
        lines.append("")
        lines.append("재시도 제안:")
        lines.extend(f"  - {s}" for s in suggestions)
    return "\n".join(lines)


def format_error(error: Exception, context: str | None = None) -> str:
    """예외를 구조화된 에러 텍스트로 변환."""
    if isinstance(error, ArchHubError):
        code, msg, suggestions = error.code, str(error), error.suggestions
    else:
        code, msg, suggestions = API_ERROR, str(error), []

    lines = [f"[{code}] {mask_key(msg)}"]
    if context:
        lines.append(f"도구: {context}")
    if suggestions:
        lines.append("제안:")
        lines.extend(f"  {i + 1}. {s}" for i, s in enumerate(suggestions))
    return "\n".join(lines)
