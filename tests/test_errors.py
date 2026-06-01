"""errors.py — 에러/응답 포맷 + 키 마스킹 단위테스트 (외부 API 비의존)."""

from archhub.errors import (
    ArchHubError, NOT_FOUND, INVALID_PARAM, NO_KEY,
    mask_key, not_found, format_error,
)


def test_mask_key_hides_service_key():
    raw = "http://api/path?serviceKey=ABC123secret&pageNo=1"
    masked = mask_key(raw)
    assert "ABC123secret" not in masked
    assert "serviceKey=***" in masked


def test_mask_key_variants_and_empty():
    assert "secret" not in mask_key("x?ServiceKey=secret")
    assert "secret" not in mask_key("x&key=secret")
    assert mask_key("") == ""


def test_not_found_has_prefix_and_warning():
    out = not_found("자료 없음", ["다시 검색"])
    assert out.startswith(f"[{NOT_FOUND}]")
    assert "추측" in out  # 환각 방지 경고
    assert "다시 검색" in out


def test_format_error_uses_code_and_masks():
    err = ArchHubError("키 없음", code=NO_KEY, suggestions=["키 설정"])
    out = format_error(err, "find_region")
    assert out.startswith(f"[{NO_KEY}]")
    assert "도구: find_region" in out
    assert "키 설정" in out


def test_format_error_masks_plain_exception():
    out = format_error(Exception("fail ?serviceKey=topsecret here"))
    assert "topsecret" not in out


def test_invalid_param_code_constant():
    err = ArchHubError("bad", code=INVALID_PARAM)
    assert format_error(err).startswith(f"[{INVALID_PARAM}]")
