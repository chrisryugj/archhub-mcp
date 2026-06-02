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
        ArchHubClient("k").query("ledger", "없는유형", "1", "1")
    assert e.value.code == INVALID_PARAM


# ---- _request_page 파싱 ----

def test_request_page_parses_list_items(monkeypatch):
    c = ArchHubClient("k")
    j = _resp({"header": {"resultCode": "00"},
               "body": {"totalCount": 2, "items": {"item": [{"a": 1}, {"a": 2}]}}})
    monkeypatch.setattr(client_mod.requests, "get", lambda *a, **k: FakeResp(j))
    df, total = c._request_page("http://x", {})
    assert total == 2 and len(df) == 2


def test_request_page_empty_data_is_not_error(monkeypatch):
    # 건축HUB는 데이터 없어도 resultCode=00 + totalCount=0 으로 준다 (실측)
    c = ArchHubClient("k")
    j = _resp({"header": {"resultCode": "00"},
               "body": {"totalCount": 0, "items": {"item": []}}})
    monkeypatch.setattr(client_mod.requests, "get", lambda *a, **k: FakeResp(j))
    df, total = c._request_page("http://x", {})
    assert total == 0 and len(df) == 0


def test_request_page_single_dict_item(monkeypatch):
    c = ArchHubClient("k")
    j = _resp({"header": {"resultCode": "00"},
               "body": {"totalCount": 1, "items": {"item": {"a": 1}}}})
    monkeypatch.setattr(client_mod.requests, "get", lambda *a, **k: FakeResp(j))
    df, total = c._request_page("http://x", {})
    assert total == 1 and len(df) == 1


def test_request_page_bad_result_code_raises(monkeypatch):
    c = ArchHubClient("k")
    j = _resp({"header": {"resultCode": "30", "resultMsg": "SERVICE KEY ERROR"}, "body": {}})
    monkeypatch.setattr(client_mod.requests, "get", lambda *a, **k: FakeResp(j))
    with pytest.raises(ArchHubError) as e:
        c._request_page("http://x", {})
    assert e.value.code == API_ERROR


def test_request_page_non_json_raises(monkeypatch):
    # 인증실패 시 HTTP 401 text/plain 'Unauthorized' (실측) → 파싱실패 에러
    c = ArchHubClient("k")
    monkeypatch.setattr(client_mod.requests, "get",
                        lambda *a, **k: FakeResp(text="Unauthorized", status=401, raise_json=True))
    with pytest.raises(ArchHubError) as e:
        c._request_page("http://x", {})
    assert e.value.code == API_ERROR
    assert "401" in str(e.value)


def test_request_page_timeout_raises(monkeypatch):
    c = ArchHubClient("k")

    def boom(*a, **k):
        raise client_mod.requests.Timeout()

    monkeypatch.setattr(client_mod.requests, "get", boom)
    with pytest.raises(ArchHubError) as e:
        c._request_page("http://x", {})
    assert e.value.code == API_ERROR


# ---- query: 페이징/절단 ----

def test_query_single_page(monkeypatch):
    c = ArchHubClient("k")
    monkeypatch.setattr(c, "_request_page", lambda url, params: (pd.DataFrame([{"x": 1}]), 1))
    df, total = c.query("ledger", "표제부", "1", "1", translate=False)
    assert total == 1 and len(df) == 1


def test_query_caps_num_rows(monkeypatch):
    # num_rows>100 요청 시 서버 상한(100)으로 캡되어 numOfRows 파라미터에 반영
    c = ArchHubClient("k")
    seen = {}

    def capture(url, params):
        seen["rows"] = params["numOfRows"]
        return pd.DataFrame([{"x": 1}]), 1

    monkeypatch.setattr(c, "_request_page", capture)
    c.query("ledger", "표제부", "1", "1", num_rows=500, translate=False)
    assert seen["rows"] == MAX_NUM_ROWS == 100


def test_fetch_all_truncates_at_max_rows(monkeypatch):
    # 큰 동(total>MAX_FETCH_ROWS)은 행 상한까지만 수집 — #2 회귀방지
    c = ArchHubClient("k")
    monkeypatch.setattr(client_mod.time, "sleep", lambda *a: None)
    page = pd.DataFrame([{"x": i} for i in range(100)])
    monkeypatch.setattr(c, "_request_page", lambda url, params: (page, 50000))
    df, total = c.query("ledger", "표제부", "1", "1", fetch_all=True, translate=False)
    assert total == 50000
    assert len(df) == MAX_FETCH_ROWS  # 10000에서 절단


def test_fetch_all_stops_when_collected_all(monkeypatch):
    # total을 다 받으면 상한 전에 종료
    c = ArchHubClient("k")
    monkeypatch.setattr(client_mod.time, "sleep", lambda *a: None)
    page = pd.DataFrame([{"x": i} for i in range(100)])
    monkeypatch.setattr(c, "_request_page", lambda url, params: (page, 250))
    df, total = c.query("ledger", "표제부", "1", "1", fetch_all=True, translate=False)
    assert total == 250 and len(df) == 300  # 100*3페이지 (got>=total에서 멈춤)


# ---- API 호출 카운터(공용키 한도 관측용) ----

def test_api_calls_counts_external_requests(monkeypatch):
    c = ArchHubClient("k")
    assert c.api_calls == 0
    j = _resp({"header": {"resultCode": "00"},
               "body": {"totalCount": 1, "items": {"item": [{"a": 1}]}}})
    monkeypatch.setattr(client_mod.requests, "get", lambda *a, **k: FakeResp(j))
    c._request_page("http://x", {})
    c._request_page("http://x", {})
    assert c.api_calls == 2  # 페이지(외부 호출)당 1 증가
