"""client.py — 입력검증·응답파싱·fetch_all 절단 단위테스트.

실제 네트워크는 monkeypatch로 차단한다. ArchHubClient 인스턴스화는
PublicDataReader 메타(meta_dict)만 쓰므로 네트워크 없이 가능하다.
"""

import pandas as pd
import pytest

from archhub import client as client_mod
from archhub.client import ArchHubClient, MAX_FETCH_ROWS, MAX_NUM_ROWS
from archhub.errors import ArchHubError, NO_KEY, INVALID_PARAM, API_ERROR


class FakeResp:
    def __init__(self, json_data=None, text="", status=200, raise_json=False):
        self._j = json_data
        self.text = text
        self.status_code = status
        self._raise = raise_json

    def json(self):
        if self._raise:
            raise ValueError("not json")
        return self._j


def _resp(j):
    return {"response": j}


# ---- find_region ----

def _bdong_client():
    """네트워크 없이 find_region을 테스트하기 위한 합성 법정동 테이블 주입."""
    c = ArchHubClient("k")
    c._bdong = pd.DataFrame([
        {"시도명": "서울특별시", "시군구명": "광진구", "읍면동명": "자양동", "동리명": "",
         "법정동코드": "1121510500"},
        {"시도명": "부산광역시", "시군구명": "해운대구", "읍면동명": "우동", "동리명": "",
         "법정동코드": "2635010100"},
    ])
    return c


def test_find_region_matches_on_sido_name():
    # 시도명(서울)을 포함한 자연스러운 입력도 매칭되어야 함(회귀: haystack에 시도명 누락 버그)
    c = _bdong_client()
    res = c.find_region("서울 광진구 자양동")
    assert len(res) == 1
    assert res.iloc[0]["sigungu_code"] == "11215"
    assert res.iloc[0]["bdong_code"] == "10500"


def test_find_region_and_terms_narrow():
    c = _bdong_client()
    assert len(c.find_region("광진구")) == 1
    assert len(c.find_region("서울 해운대구")) == 0  # 시도+시군구 AND 불일치


# ---- 입력검증 ----

def test_query_requires_service_key():
    with pytest.raises(ArchHubError) as e:
        ArchHubClient("").query("ledger", "표제부", "1", "1")
    assert e.value.code == NO_KEY


def test_query_rejects_unknown_kind():
    with pytest.raises(ArchHubError) as e:
        ArchHubClient("k").query("nope", "표제부", "1", "1")
    assert e.value.code == INVALID_PARAM


def test_query_rejects_unknown_type():
    with pytest.raises(ArchHubError) as e:
        ArchHubClient("k").query("ledger", "없는유형", "11215", "10500")
    assert e.value.code == INVALID_PARAM


@pytest.mark.parametrize("sg,bd", [("1", "10500"), ("11215", "abc"), ("112150", "10500"), ("", "10500")])
def test_query_rejects_malformed_codes(sg, bd):
    # #7: 5자리 숫자가 아니면 외부 API 호출 전에 INVALID_PARAMETER로 차단
    with pytest.raises(ArchHubError) as e:
        ArchHubClient("k").query("ledger", "표제부", sg, bd)
    assert e.value.code == INVALID_PARAM


def test_query_upgrades_http_to_https(monkeypatch):
    # #4: meta_dict의 http 엔드포인트를 https로 승격해 호출
    c = ArchHubClient("k")
    seen = {}

    def capture(url, params):
        seen["url"] = url
        return pd.DataFrame([{"x": 1}]), 1

    monkeypatch.setattr(c, "_request_page", capture)
    c.query("ledger", "표제부", "11215", "10500", translate=False)
    assert seen["url"].startswith("https://")


def test_fetch_all_stops_at_max_pages(monkeypatch):
    # #3: total이 무한정이어도 페이지 상한에서 멈춰 워커 폭주 방지
    c = ArchHubClient("k")
    monkeypatch.setattr(client_mod.time, "sleep", lambda *a: None)
    calls = {"n": 0}

    def capture(url, params):
        calls["n"] += 1
        return pd.DataFrame([{"x": i} for i in range(100)]), 10_000_000

    monkeypatch.setattr(c, "_request_page", capture)
    c.query("ledger", "표제부", "11215", "10500", fetch_all=True, translate=False)
    assert calls["n"] <= client_mod.MAX_FETCH_PAGES


def test_daily_cap_blocks_when_exceeded(monkeypatch):
    # #1: 일일 호출 캡 초과 시 EXTERNAL_API_ERROR로 차단
    monkeypatch.setattr(client_mod, "DAILY_CALL_CAP", 2)
    c = ArchHubClient("k")
    j = _resp({"header": {"resultCode": "00"},
               "body": {"totalCount": 1, "items": {"item": [{"a": 1}]}}})
    monkeypatch.setattr(c._session, "get", lambda *a, **k: FakeResp(j))
    c._request_page("http://x", {})
    c._request_page("http://x", {})
    with pytest.raises(ArchHubError) as e:
        c._request_page("http://x", {})
    assert e.value.code == API_ERROR


# ---- _request_page 파싱 ----

def test_request_page_parses_list_items(monkeypatch):
    c = ArchHubClient("k")
    j = _resp({"header": {"resultCode": "00"},
               "body": {"totalCount": 2, "items": {"item": [{"a": 1}, {"a": 2}]}}})
    monkeypatch.setattr(c._session, "get", lambda *a, **k: FakeResp(j))
    df, total = c._request_page("http://x", {})
    assert total == 2 and len(df) == 2


def test_request_page_empty_data_is_not_error(monkeypatch):
    # 건축HUB는 데이터 없어도 resultCode=00 + totalCount=0 으로 준다 (실측)
    c = ArchHubClient("k")
    j = _resp({"header": {"resultCode": "00"},
               "body": {"totalCount": 0, "items": {"item": []}}})
    monkeypatch.setattr(c._session, "get", lambda *a, **k: FakeResp(j))
    df, total = c._request_page("http://x", {})
    assert total == 0 and len(df) == 0


def test_request_page_single_dict_item(monkeypatch):
    c = ArchHubClient("k")
    j = _resp({"header": {"resultCode": "00"},
               "body": {"totalCount": 1, "items": {"item": {"a": 1}}}})
    monkeypatch.setattr(c._session, "get", lambda *a, **k: FakeResp(j))
    df, total = c._request_page("http://x", {})
    assert total == 1 and len(df) == 1


def test_request_page_bad_result_code_raises(monkeypatch):
    c = ArchHubClient("k")
    j = _resp({"header": {"resultCode": "30", "resultMsg": "SERVICE KEY ERROR"}, "body": {}})
    monkeypatch.setattr(c._session, "get", lambda *a, **k: FakeResp(j))
    with pytest.raises(ArchHubError) as e:
        c._request_page("http://x", {})
    assert e.value.code == API_ERROR


def test_request_page_non_json_raises(monkeypatch):
    # 인증실패 시 HTTP 401 text/plain 'Unauthorized' (실측) → 파싱실패 에러
    c = ArchHubClient("k")
    monkeypatch.setattr(c._session, "get",
                        lambda *a, **k: FakeResp(text="Unauthorized", status=401, raise_json=True))
    with pytest.raises(ArchHubError) as e:
        c._request_page("http://x", {})
    assert e.value.code == API_ERROR
    assert "401" in str(e.value)


def test_request_page_timeout_raises(monkeypatch):
    c = ArchHubClient("k")

    def boom(*a, **k):
        raise client_mod.requests.Timeout()

    monkeypatch.setattr(c._session, "get", boom)
    with pytest.raises(ArchHubError) as e:
        c._request_page("http://x", {})
    assert e.value.code == API_ERROR


# ---- query: 페이징/절단 ----

def test_query_single_page(monkeypatch):
    c = ArchHubClient("k")
    monkeypatch.setattr(c, "_request_page", lambda url, params: (pd.DataFrame([{"x": 1}]), 1))
    df, total = c.query("ledger", "표제부", "11215", "10500", translate=False)
    assert total == 1 and len(df) == 1


def test_query_caps_num_rows(monkeypatch):
    # num_rows>100 요청 시 서버 상한(100)으로 캡되어 numOfRows 파라미터에 반영
    c = ArchHubClient("k")
    seen = {}

    def capture(url, params):
        seen["rows"] = params["numOfRows"]
        return pd.DataFrame([{"x": 1}]), 1

    monkeypatch.setattr(c, "_request_page", capture)
    c.query("ledger", "표제부", "11215", "10500", num_rows=500, translate=False)
    assert seen["rows"] == MAX_NUM_ROWS == 100


def test_fetch_all_truncates_at_max_rows(monkeypatch):
    # 큰 동(total>MAX_FETCH_ROWS)은 행 상한까지만 수집 — #2 회귀방지
    c = ArchHubClient("k")
    monkeypatch.setattr(client_mod.time, "sleep", lambda *a: None)
    page = pd.DataFrame([{"x": i} for i in range(100)])
    monkeypatch.setattr(c, "_request_page", lambda url, params: (page, 50000))
    df, total = c.query("ledger", "표제부", "11215", "10500", fetch_all=True, translate=False)
    assert total == 50000
    assert len(df) == MAX_FETCH_ROWS  # 10000에서 절단


def test_fetch_all_stops_when_collected_all(monkeypatch):
    # total을 다 받으면 상한 전에 종료
    c = ArchHubClient("k")
    monkeypatch.setattr(client_mod.time, "sleep", lambda *a: None)
    page = pd.DataFrame([{"x": i} for i in range(100)])
    monkeypatch.setattr(c, "_request_page", lambda url, params: (page, 250))
    df, total = c.query("ledger", "표제부", "11215", "10500", fetch_all=True, translate=False)
    assert total == 250 and len(df) == 300  # 100*3페이지 (got>=total에서 멈춤)


# ---- API 호출 카운터(공용키 한도 관측용) ----

def test_api_calls_counts_external_requests(monkeypatch):
    c = ArchHubClient("k")
    assert c.api_calls == 0
    j = _resp({"header": {"resultCode": "00"},
               "body": {"totalCount": 1, "items": {"item": [{"a": 1}]}}})
    monkeypatch.setattr(c._session, "get", lambda *a, **k: FakeResp(j))
    c._request_page("http://x", {})
    c._request_page("http://x", {})
    assert c.api_calls == 2  # 페이지(외부 호출)당 1 증가
