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


def test_find_region_parses_bunji(monkeypatch):
    # "자양동 680-63" — 번지를 분리해 지역만 검색하고 bun/ji 사용법을 안내
    _patch_bdong(monkeypatch)
    out = server.find_region("자양동 680-63")
    assert "자양동" in out
    assert "bun=680" in out and "ji=63" in out


def test_find_region_parses_bun_only_with_suffix(monkeypatch):
    _patch_bdong(monkeypatch)
    out = server.find_region("자양동 680번지")
    assert "bun=680" in out and "ji=" not in out


def test_find_region_bunji_only_is_not_found(monkeypatch):
    # 번지만 있으면 지역 검색 불가(전체 테이블 반환 방지)
    _patch_bdong(monkeypatch)
    out = server.find_region("680-63")
    assert "[NOT_FOUND]" in out and "지역 키워드" in out


# ---- parcel_history / temp_buildings 도구 ----

def _route_query(responses):
    """type_name별로 다른 DataFrame을 돌려주는 client.query 대역."""
    def q(kind, type_name, *a, **k):
        df = responses.get(type_name, pd.DataFrame())
        return df, len(df)
    return q


def test_parcel_history_requires_bun():
    out = server.parcel_history("11215", "10500", bun=" ")
    assert "[NOT_FOUND]" in out and "번지(bun)" in out


def test_parcel_history_merges_three_sources(monkeypatch):
    yr = datetime.date.today().year
    monkeypatch.setattr(server.client, "query", _route_query({
        "기본개요": pd.DataFrame([
            {"관리허가대장PK": "N1", "건축구분코드": "신축", "주용도코드명": "업무시설",
             "건축허가일": f"{yr - 3}0418", "실제착공일": " ", "사용승인일": " ",
             "연면적(㎡)": "1000", "건물명": "신축빌"},
        ]),
        "철거멸실관리대장": pd.DataFrame([
            {"철거멸실구분코드명": "철거", "철거시작일": f"{yr - 5}0301",
             "주용도코드명": "단독주택", "연면적(㎡)": "100"},
        ]),
        "가설건축물": pd.DataFrame([
            {"관리허가대장PK": "T1", "구조코드명": "컨테이너조",
             "전체연면적(㎡)": "36", "가설건축물존치만료일": f"{yr + 1}0101"},
        ]),
    }))
    out = server.parcel_history("11215", "10500", bun="2", ji="2")
    assert "[필지 연혁] 2-2" in out
    assert "신축" in out and "철거멸실" in out and "가설건축물" in out
    # 철거(yr-5)가 신축 허가(yr-3)보다 먼저(오래된 순)
    assert out.index("철거멸실") < out.index("신축")


def test_parcel_history_all_empty_not_found(monkeypatch):
    monkeypatch.setattr(server.client, "query", _route_query({}))
    out = server.parcel_history("11215", "10500", bun="9", ji="9")
    assert "[NOT_FOUND]" in out


def test_temp_buildings_tool(monkeypatch):
    df = pd.DataFrame([
        {"관리허가대장PK": "P1", "대지위치": "자양동 2-2번지", "구조코드명": "컨테이너조",
         "주용도코드명": "가설건축물", "전체연면적(㎡)": "171",
         "가설건축물존치만료일": "20220820"},
    ])
    monkeypatch.setattr(server.client, "query", lambda *a, **k: (df, len(df)))
    out = server.temp_buildings("11215", "10500")
    assert "존치만료 경과 1건" in out and "2-2번지" in out


def test_temp_buildings_empty_not_found(monkeypatch):
    monkeypatch.setattr(server.client, "query", lambda *a, **k: (pd.DataFrame(), 0))
    out = server.temp_buildings("11215", "10500")
    assert "[NOT_FOUND]" in out


def test_building_profile_includes_zoning_and_septic(monkeypatch):
    # 표제부 + 지역지구구역 + 오수정화시설(정화조) 3원천이 종합카드에 합쳐진다
    monkeypatch.setattr(server.client, "query", _route_query({
        "표제부": pd.DataFrame([{"건물명": "테스트빌", "주용도코드명": "업무시설"}]),
        "지역지구구역": pd.DataFrame([
            {"지역지구구역코드명": "일반상업지역", "대표여부": "1"},
        ]),
        "오수정화시설": pd.DataFrame([
            {"형식코드명": "부패탱크방법", "용량(인용)": "2000", "용량(루베)": "0"},
        ]),
    }))
    out = server.building_profile("11215", "10500", bun="2", ji="2")
    assert "용도지역·지구: 일반상업지역" in out
    assert "정화조: 부패탱크방법 2000인용" in out


def test_building_profile_omits_septic_when_absent(monkeypatch):
    monkeypatch.setattr(server.client, "query", _route_query({
        "표제부": pd.DataFrame([{"건물명": "테스트빌"}]),
    }))
    out = server.building_profile("11215", "10500", bun="2")
    assert "정화조" not in out  # 부가정보 없으면 조용히 생략


# ---- building_data (raw 3종 통합 도구) ----

def test_building_data_rejects_unknown_kind():
    out = server.building_data("license", "표제부", "11215", "10500")
    assert "[NOT_FOUND]" in out and "ledger" in out


def test_building_data_routes_kind_to_query(monkeypatch):
    seen = {}

    def fake_query(kind, type_name, *a, **k):
        seen["kind"], seen["type_name"] = kind, type_name
        return pd.DataFrame([{"건물명": "테스트빌"}]), 1

    monkeypatch.setattr(server.client, "query", fake_query)
    out = server.building_data("housing", "동별개요", "11215", "10500")
    assert seen == {"kind": "housing", "type_name": "동별개요"}
    assert "테스트빌" in out and "유형=동별개요" in out


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
