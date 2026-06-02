"""formatting.py — 카드 포맷터·헬퍼 단위테스트 (외부 API 비의존)."""

import pandas as pd

from archhub.formatting import (
    _num, _g, _date, _area, _pct, building_card, profile_to_text,
    district_to_text, df_to_text, SOURCE,
)
import datetime


def test_num_treats_zero_and_blank_as_none():
    assert _num("123.5") == 123.5
    assert _num("1,000") == 1000.0
    assert _num("0") is None      # 미기재 취급
    assert _num("") is None
    assert _num("abc") is None


def test_g_filters_blank_nan_zero():
    row = pd.Series({"a": "값", "b": "", "c": "nan", "d": "0"})
    assert _g(row, "a") == "값"
    assert _g(row, "b") is None
    assert _g(row, "c") is None
    assert _g(row, "d") is None
    assert _g(row, "missing") is None


def test_date_formats_yyyymmdd():
    assert _date("19810204") == "1981-02-04"
    assert _date("20231114") == "2023-11-14"
    assert _date("") is None
    assert _date("abc") is None


def test_area_format():
    assert _area("1762.88") == "1,762.88㎡"
    assert _area("0") is None


def test_building_card_computes_bcr_far_when_missing():
    row = pd.Series({
        "건물명": "테스트빌", "대지면적": "1000", "건축면적": "600",
        "연면적": "4000", "용적률산정연면적": "2500", "건폐율": "0", "용적률": "0",
        "옥내자주식대수": "30", "옥외자주식대수": "5",
        "옥내기계식대수": "0", "옥외기계식대수": "0",
        "사용승인일": "20231114",
    })
    card = building_card(row)
    assert "건폐율 60.0%(계산)" in card     # 600/1000
    assert "용적률 250.0%(계산)" in card    # 2500/1000
    assert "자주식 35대" in card            # 30+5 합산
    assert "사용승인 2023-11-14" in card


def test_building_card_prefers_reported_ratio():
    row = pd.Series({"건물명": "A", "대지면적": "1000", "건축면적": "600", "건폐율": "55", "용적률": "200"})
    card = building_card(row)
    assert "건폐율 55%" in card and "계산" not in card.split("건폐율")[1].split("·")[0]


def test_building_card_omits_missing_fields():
    row = pd.Series({"건물명": "B"})  # 거의 빈 행
    card = building_card(row)
    assert card.startswith("■ B")
    assert "규모" not in card  # 값 없으면 줄 생략


def test_building_card_fallback_name():
    row = pd.Series({"동명칭": "101동"})
    assert "■ 101동" in building_card(row)
    assert "■ (건물명 없음)" in building_card(pd.Series({"대지위치": "x"}))


def test_profile_to_text_truncation_note():
    df = pd.DataFrame([{"건물명": f"동{i}"} for i in range(10)])
    out = profile_to_text(df, total=10, max_buildings=3)
    assert "10개 동" in out and "3개 표시" in out
    assert SOURCE in out
    assert out.count("■") == 3


def test_pct():
    assert _pct(25, 100) == "25.0%"
    assert _pct(1, 3) == "33.3%"
    assert _pct(7, 100) == " 7.0%"   # 한 자리는 폭4로 좌측 공백 정렬
    assert _pct(5, 0) == " 0.0%"     # total=0 → 0.0%


def test_district_to_text_aggregates():
    yr = datetime.date.today().year
    df = pd.DataFrame([
        {"주용도코드명": "단독주택", "연면적": "100", "지상층수": "2", "사용승인일": f"{yr-45}0101"},
        {"주용도코드명": "단독주택", "연면적": "200", "지상층수": "3", "사용승인일": f"{yr-35}0101"},
        {"주용도코드명": "공동주택", "연면적": "1,000", "지상층수": "15", "사용승인일": f"{yr-5}0101"},
        {"주용도코드명": "", "연면적": "", "지상층수": "", "사용승인일": ""},  # 미상 행
    ])
    out = district_to_text(df, total=4, min_age_years=30)
    assert "총 4동" in out
    assert "총 연면적 1,300㎡" in out          # 100+200+1000
    assert "단독주택" in out and "2동" in out
    assert "공동주택" in out
    assert "(미상)" in out                     # 용도/연도/노후 미상 처리
    assert "40년 이상" in out and "⚠" in out    # 노후 마킹
    assert "→ 경과 30년↑ 합계 2동" in out       # 45년·35년 두 동
    assert SOURCE in out


def test_district_to_text_handles_empty_optional_columns():
    # 표제부에 일부 컬럼이 없어도 죽지 않는다(빈 시리즈 fallback)
    df = pd.DataFrame([{"주용도코드명": "단독주택"}, {"주용도코드명": "단독주택"}])
    out = district_to_text(df, total=2)
    assert "총 2동" in out and "단독주택" in out


def test_df_to_text_empty_and_source():
    assert "0건" in df_to_text(pd.DataFrame())
    out = df_to_text(pd.DataFrame([{"a": 1}, {"a": 2}]), max_rows=1)
    assert "상위 1건" in out and SOURCE in out
