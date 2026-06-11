"""server.py — 키 만료 D-day 계산·도구 출력 단위테스트 (외부 API 비의존).

server import 시 ArchHubClient는 메타(meta_dict)만 쓰므로 네트워크 없이 가능하다.
"""

import datetime

import pandas as pd

from archhub import server


def test_key_expiry_none_when_unset(monkeypatch):
    monkeypatch.setattr(server, "KEY_EXPIRES", "")
    assert server._key_expiry_days() is None


def test_key_expiry_none_on_bad_format(monkeypatch):
    monkeypatch.setattr(server, "KEY_EXPIRES", "2028/06/02")  # ISO 아님
    assert server._key_expiry_days() is None


def test_key_expiry_future_days(monkeypatch):
    future = (datetime.date.today() + datetime.timedelta(days=10)).isoformat()
    monkeypatch.setattr(server, "KEY_EXPIRES", future)
    assert server._key_expiry_days() == 10


def test_key_expiry_past_is_negative(monkeypatch):
    past = (datetime.date.today() - datetime.timedelta(days=5)).isoformat()
    monkeypatch.setattr(server, "KEY_EXPIRES", past)
    assert server._key_expiry_days() == -5


# ---- find_region 도구 ----

def _patch_bdong(monkeypatch):
    """네트워크 없이 find_region 도구를 테스트하기 위한 합성 법정동 테이블 주입."""
    monkeypatch.setattr(server.client, "_bdong", pd.DataFrame([
        # 구 단위 행: 읍면동명·동리명 모두 공백 → bdong_code='00000'
        {"시도명": "서울특별시", "시군구명": "광진구", "읍면동명": "", "동리명": "",
         "법정동코드": "1121500000"},
        {"시도명": "서울특별시", "시군구명": "광진구", "읍면동명": "자양동", "동리명": "",
         "법정동코드": "1121510500"},
    ]))


def test_find_region_marks_gu_level_rows(monkeypatch):
    # 읍면동명·동리명 모두 공백인 시군구 단위 행은 bdong_code로 사용 불가 표시 (#A9a)
    _patch_bdong(monkeypatch)
    out = server.find_region("광진구")
    assert "구 단위 — bdong_code로 사용 불가" in out
    assert "자양동" in out  # 동 단위 행은 정상 노출


def test_find_region_no_result_suggests_beopjeongdong(monkeypatch):
    # 행정동(자양1동)으로 검색해 0건이면 법정동(자양동) 재검색 안내 (#A9b)
    _patch_bdong(monkeypatch)
    out = server.find_region("자양1동")
    assert "[NOT_FOUND]" in out
    assert "행정동" in out and "법정동이 아님" in out


# ---- permits_pipeline 기본 since_year ----

def test_permits_pipeline_defaults_to_recent_5_years(monkeypatch):
    # since_year=0(기본)은 전체가 아니라 최근 5년 — 실효·미착공 허가 과대집계 방지 (#A3)
    yr = datetime.date.today().year
    df = pd.DataFrame([
        {"대지위치": "자양동 1-1", "건물명": "최근빌", "건축구분코드": "신축",
         "주용도코드명": "업무시설", "건축허가일": f"{yr}0102", "실제착공일": f"{yr}0301", "사용승인일": " "},
        {"대지위치": "자양동 2-2", "건물명": "옛날착공빌", "건축구분코드": "신축",
         "주용도코드명": "업무시설", "건축허가일": f"{yr - 10}0101", "실제착공일": f"{yr - 9}0101", "사용승인일": " "},
    ])
    monkeypatch.setattr(server.client, "query", lambda *a, **k: (df, len(df)))
    out = server.permits_pipeline("11215", "10500")
    assert f"허가 {yr - 5}년↑" in out          # 기본 = 최근 5년
    assert "최근빌" in out and "옛날착공빌" not in out
    # 과거 연도를 지정하면 전체 조회 가능
    out_all = server.permits_pipeline("11215", "10500", since_year=1900)
    assert "옛날착공빌" in out_all
