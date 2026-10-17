"""MCP 프로토콜 수준 회귀 — 외부 API 실패는 isError=true, 성공·0건은 isError=false (gomdori-mcp#4).

in-memory fastmcp Client로 실제 tools/call 경로를 탄다. HTTP 계층(requests.Session.get)만 바꿔
끼워 연결 시간 초과 등을 주입하므로 실제 네트워크 호출은 없다.
"""

import asyncio
import logging

import pytest
import requests
from fastmcp import Client

from archhub import client as client_mod
from archhub import server

FAKE_KEY = "TEST_SECRET_KEY"
SITE = {"sigungu_code": "11215", "bdong_code": "10500"}
PARCEL = {**SITE, "bun": "2"}
# gomdori-mcp#4 재현 입력 그대로
REPRO = {"kind": "ledger", "type_name": "표제부", "sigungu_code": "11140", "bdong_code": "10300",
         "bun": "0031", "ji": "0000", "max_rows": 1, "page": 1}

DATA_TOOLS = [
    ("building_data", REPRO),
    ("building_profile", PARCEL),
    ("building_floors", PARCEL),
    ("price_history", PARCEL),
    ("parcel_history", PARCEL),
    ("temp_buildings", SITE),
    ("old_buildings", SITE),
    ("district_stats", SITE),
    ("demolitions", SITE),
    ("permits_pipeline", SITE),
    ("seismic_check", SITE),
]


class _Resp:
    def __init__(self, status=200, json_data=None):
        self.status_code = status
        self._j = json_data

    def json(self):
        if self._j is None:
            raise ValueError("not json")
        return self._j


def _ok(items, total=None):
    return _Resp(200, {"response": {"header": {"resultCode": "00"},
                                    "body": {"totalCount": len(items) if total is None else total,
                                             "items": {"item": items} if items else ""}}})


def _raise(exc):
    def get(*a, **k):
        raise exc
    return get


@pytest.fixture
def http(monkeypatch):
    """server.client의 HTTP 계층만 바꿔 끼운다. 키·응답 캐시는 테스트마다 격리."""
    monkeypatch.setattr(server.client, "service_key", FAKE_KEY)
    monkeypatch.setattr(server.client, "_cache", client_mod._TTLCache())

    def install(get):
        monkeypatch.setattr(server.client._session, "get", get)
    return install


def _call(name, args):
    async def run():
        async with Client(server.mcp) as c:
            return await c.call_tool(name, args, raise_on_error=False)
    res = asyncio.run(run())
    return res.is_error, res.content[0].text


@pytest.mark.parametrize("name,args", DATA_TOOLS)
def test_connect_timeout_is_mcp_error(http, name, args):
    # 연결 시간 초과(TCP 443, gomdori-mcp#4 운영 장애 형태) → 모든 데이터 도구가 isError=true
    http(_raise(requests.ConnectTimeout("connect timed out")))
    is_error, text = _call(name, args)
    assert is_error is True
    assert text.startswith("[EXTERNAL_API_ERROR] API 응답 시간 초과")


def test_connection_error_is_mcp_error_and_key_stays_masked(http, caplog):
    # requests 메시지엔 serviceKey가 든 URL이 실린다 — 결과 본문·로그 어디에도 키 평문이 없어야 한다
    msg = (f"HTTPSConnectionPool(host='apis.data.go.kr', port=443): Max retries exceeded with url: "
           f"/1613000/BldRgstHubService/getBrTitleInfo?serviceKey={FAKE_KEY}&pageNo=1")
    http(_raise(requests.ConnectionError(msg)))
    with caplog.at_level(logging.WARNING, logger="archhub"):
        is_error, text = _call("building_data", REPRO)
    assert is_error is True
    assert "[EXTERNAL_API_ERROR] API 요청 실패" in text
    assert FAKE_KEY not in text
    assert "외부 API 요청 실패" in caplog.text and FAKE_KEY not in caplog.text


@pytest.mark.parametrize("resp", [
    _Resp(502),                                                    # 게이트웨이 장애(비JSON 본문)
    _Resp(200, {"response": {"header": {"resultCode": "99", "resultMsg": "SERVICE ERROR"}}}),
])
def test_http_and_result_code_errors_are_mcp_errors(http, resp):
    http(lambda *a, **k: resp)
    is_error, text = _call("district_stats", SITE)
    assert is_error is True and text.startswith("[EXTERNAL_API_ERROR]")


def test_zero_result_stays_normal_not_found(http):
    # 데이터 없음(resultCode=00 + totalCount=0, 실측)은 오류가 아니다 — [NOT_FOUND] 일반 결과
    http(lambda *a, **k: _ok([]))
    is_error, text = _call("building_data", REPRO)
    assert is_error is False and text.startswith("[NOT_FOUND]")


def test_success_stays_normal(http):
    http(lambda *a, **k: _ok([{"bldNm": "테스트빌", "platPlc": "서울특별시 중구 을지로1가 31번지"}]))
    is_error, text = _call("building_data", REPRO)
    assert is_error is False and "테스트빌" in text


def test_invalid_parameter_is_mcp_error(http):
    # 입력 오류도 도구 실패 — [INVALID_PARAMETER] 본문 그대로 isError=true (외부 호출 전 차단)
    http(_raise(AssertionError("외부 호출이 일어나면 안 됨")))
    is_error, text = _call("district_stats", {"sigungu_code": "abc", "bdong_code": "10500"})
    assert is_error is True and text.startswith("[INVALID_PARAMETER]")


def test_find_region_download_timeout_is_mcp_error(monkeypatch, tmp_path):
    # 법정동코드 JSON을 받지 못하면(캐시 없음 + 다운로드 시간 초과) find_region도 isError=true
    monkeypatch.setattr(server.client, "_bdong", None)
    monkeypatch.setattr(client_mod, "BDONG_CACHE_PATH", tmp_path / "code_bdong.json")
    monkeypatch.setattr(client_mod.requests, "get", _raise(requests.ConnectTimeout("connect timed out")))
    is_error, text = _call("find_region", {"keyword": "광진구 자양동"})
    assert is_error is True and text.startswith("[EXTERNAL_API_ERROR] 법정동코드 데이터를 받지 못했습니다")
