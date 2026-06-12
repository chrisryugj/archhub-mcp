"""formatting.py — 카드 포맷터·헬퍼 단위테스트 (외부 API 비의존)."""

import pandas as pd

from archhub.formatting import (
    _num, _g, _date, _area, _eok, _year_of, _pct, _floor_sort_key, _sample_trend,
    _permit_kind, _prune_columns, building_card, profile_to_text, district_to_text,
    floors_to_text, price_history_to_text, demolitions_to_text, pipeline_to_text,
    parcel_history_to_text, temp_buildings_to_text, df_to_text, SOURCE,
)
import datetime


def test_num_treats_zero_and_blank_as_none():
    assert _num("123.5") == 123.5
    assert _num("1,000") == 1000.0
    assert _num("0") is None      # 미기재 취급
    assert _num("") is None
    assert _num("abc") is None
    assert _num("nan") is None            # float('nan') 파싱 성공 케이스 차단
    assert _num(float("nan")) is None     # 결측 셀(NaN) — 미기재 취급


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


def test_profile_to_text_notes_violation_unavailable():
    # 위반건축물은 본 API 미제공 — 카드에 한계를 명시해 '미표시=위반없음' 오해 방지
    out = profile_to_text(pd.DataFrame([{"건물명": "A"}]), total=1, max_buildings=5)
    assert "위반건축물" in out and "제공하지 않습니다" in out


def test_profile_multi_building_calc_note():
    # 다동 필지 + 건폐율 계산값(미기재라 면적계산)이면 '동별 값' 주석을 붙인다 (M2)
    df = pd.DataFrame([
        {"건물명": "A동", "대지면적": "1000", "건축면적": "600"},  # 건폐율 60%(계산)
        {"건물명": "B동", "대지면적": "1000", "건축면적": "300"},  # 건폐율 30%(계산)
    ])
    out = profile_to_text(df, total=2, max_buildings=5)
    assert "(계산)" in out
    assert "필지 전체 합산이 아닙니다" in out
    # 단동이면 주석 없음
    assert "필지 전체 합산이 아닙니다" not in profile_to_text(df.head(1), total=1, max_buildings=5)


def test_profile_to_text_shows_zoning():
    df = pd.DataFrame([{"건물명": "A"}])
    out = profile_to_text(df, total=1, max_buildings=5, zoning="제2종일반주거지역 · 지구단위계획구역")
    assert "용도지역·지구: 제2종일반주거지역 · 지구단위계획구역" in out
    # zoning 없으면 줄 생략
    assert "용도지역" not in profile_to_text(df, total=1, max_buildings=5)


def test_floor_sort_key_orders_top_to_bottom():
    # 옥탑 > 지상2 > 지상1 > 지하1 > 지하2
    keys = [
        _floor_sort_key("옥탑", 1), _floor_sort_key("지상", 2), _floor_sort_key("지상", 1),
        _floor_sort_key("지하", 1), _floor_sort_key("지하", 2),
    ]
    assert keys == sorted(keys, reverse=True)


def test_floors_to_text_stacks_sorts_and_merges():
    df = pd.DataFrame([
        {"건물명": "테스트빌", "층구분코드명": "지상", "층번호": "1", "주용도코드명": "근린생활시설", "면적": "100"},
        {"건물명": "테스트빌", "층구분코드명": "지상", "층번호": "1", "주용도코드명": "주차장", "면적": "50"},
        {"건물명": "테스트빌", "층구분코드명": "지상", "층번호": "2", "주용도코드명": "사무소", "면적": "150"},
        {"건물명": "테스트빌", "층구분코드명": "지하", "층번호": "1", "주용도코드명": "주차장", "면적": "200"},
        {"건물명": "테스트빌", "층구분코드명": "옥탑", "층번호": "1", "주용도코드명": "기계실", "면적": "20"},
    ])
    out = floors_to_text(df, total=5)
    order = [ln for ln in out.splitlines() if "㎡" in ln and ("층" in ln or "옥탑" in ln)]
    assert "옥탑" in order[0] and "2층" in order[1] and "1층" in order[2] and "지하1층" in order[3]
    assert "근린생활시설 100㎡" in out and "주차장 50㎡" in out  # 같은 층 복수용도 나열
    assert "■ 층별 구성 — 테스트빌" in out and SOURCE in out


def test_floors_to_text_splits_multi_dong():
    # 다동 필지: 동 구분 없이 층을 합산하면 101동 1층 + 102동 1층이 한 줄로 합쳐진다(버그) →
    # 동명칭이 2개 이상이면 동별 섹션으로 분리한다 (#A2)
    df = pd.DataFrame([
        {"건물명": "쌍둥이빌", "동명칭": "101동", "층구분코드명": "지상", "층번호": "1",
         "주용도코드명": "공동주택", "면적": "100"},
        {"건물명": "쌍둥이빌", "동명칭": "101동", "층구분코드명": "지상", "층번호": "2",
         "주용도코드명": "공동주택", "면적": "100"},
        {"건물명": "쌍둥이빌", "동명칭": "102동", "층구분코드명": "지상", "층번호": "1",
         "주용도코드명": "공동주택", "면적": "300"},
    ])
    out = floors_to_text(df, total=3)
    assert "[101동]" in out and "[102동]" in out
    # 동별 면적이 합산되지 않는다: 101동 1층 100㎡, 102동 1층 300㎡ (합산 400㎡ 없음)
    assert "100㎡" in out and "300㎡" in out
    assert "400" not in out
    # 단동이면 기존 동작(섹션 없음)
    single = floors_to_text(df[df["동명칭"] == "101동"], total=2)
    assert "[101동]" not in single and "총 2개 층" in single


def test_floors_to_text_appends_etc_use():
    # 기타용도가 있으면 주용도 옆에 병기 (예: 제2종근린생활시설(고시원))
    df = pd.DataFrame([
        {"건물명": "A", "층구분코드명": "지상", "층번호": "2",
         "주용도코드명": "제2종근린생활시설", "기타용도": "고시원", "면적": "150"},
        {"건물명": "A", "층구분코드명": "지상", "층번호": "1",
         "주용도코드명": "제1종근린생활시설", "기타용도": "", "면적": "150"},
    ])
    out = floors_to_text(df, total=2)
    assert "제2종근린생활시설(고시원) 150㎡" in out
    assert "제1종근린생활시설 150㎡" in out  # 기타용도 없으면 병기 없음


def test_floors_to_text_survives_missing_use_column():
    # 주용도코드명 컬럼이 아예 없어도 죽지 않는다(결측 방어 통일)
    df = pd.DataFrame([{"건물명": "A", "층구분코드명": "지상", "층번호": "1", "면적": "100"}])
    out = floors_to_text(df, total=1)
    assert "1층" in out and "100㎡" in out


def test_eok_format():
    assert _eok("429000000") == "4.29억"
    assert _eok(245000000) == "2.45억"
    assert _eok("0") is None
    assert _eok("") is None


def test_sample_trend_keeps_first_and_last():
    # 6개 이하는 전부 표시
    pts = [(2009, 2.45e8), (2017, 3.0e8), (2025, 4.29e8)]
    s = _sample_trend(pts)
    assert "'09 2.45억" in s and "'25 4.29억" in s and "→" in s
    # 6개 초과는 최초·최신 포함해 균등 샘플(최초/최신 항상 등장)
    many = [(2009 + i, (2.3 + i * 0.1) * 1e8) for i in range(17)]  # 2009~2025
    s2 = _sample_trend(many, max_points=6)
    assert "'09" in s2 and "'25" in s2
    assert s2.count("→") <= 5  # 최대 6포인트 = 화살표 5개 이하


def _price_df():
    """주택가격 type 합성 — 2호(PK 1001/1002) × 3연도."""
    rows = []
    for pk, base in [(1001, 2.0e8), (1002, 3.0e8)]:
        for yr, mult in [(2015, 1.0), (2020, 1.2), (2025, 1.5)]:
            rows.append({
                "관리건축물대장PK": pk, "주택가격": int(base * mult),
                "stdDay": f"{yr}0101", "새주소본번": "22", "새주소부번": "0",
            })
    return pd.DataFrame(rows)


def test_price_history_groups_by_unit_and_computes_change():
    out = price_history_to_text(_price_df(), total=6, top_units=10, bun="24", ji="28")
    assert "주택가격 6건 · 2호" in out
    # 최신가 높은 호(PK1002, 4.50억)가 먼저
    assert out.index("PK…1002") < out.index("PK…1001")
    # 총증감률: 2.0→3.0억 = +50.0%, 10년
    assert "최신 3.00억 (2025)" in out and "최초 2.00억 (2015)" in out
    assert "10년간 +50.0%" in out
    assert "연평균" in out          # CAGR 산출
    assert "추이:" in out and "'15" in out and "'25" in out
    assert SOURCE in out


def test_price_history_top_units_truncates():
    out = price_history_to_text(_price_df(), total=6, top_units=1, bun="24")
    assert "상위 1호 표시" in out
    assert out.count("■") == 1     # 1호만


def test_price_history_empty():
    out = price_history_to_text(pd.DataFrame(), total=0, top_units=10, bun="24")
    assert "[NOT_FOUND]" in out and "0건" in out


def test_price_history_all_zero_prices_uses_not_found():
    # 행은 있으나 유효 가격(>0)이 없어 필터 후 0건 → 평문이 아닌 [NOT_FOUND] + 환각경고 (M3)
    df = pd.DataFrame([
        {"관리건축물대장PK": 1, "주택가격": 0, "stdDay": "20200101"},
        {"관리건축물대장PK": 1, "주택가격": "", "stdDay": "20210101"},
    ])
    out = price_history_to_text(df, total=2, top_units=10, bun="24")
    assert "[NOT_FOUND]" in out and "추측" in out


def test_price_history_warns_not_market_price():
    # 공시가격≠시세 경고를 정상 출력 말미에 명시 (M1)
    out = price_history_to_text(_price_df(), total=6, top_units=10, bun="24")
    assert "공시가격은 시세가 아닙니다" in out


def test_year_of():
    assert _year_of("20190301") == 2019
    assert _year_of("2019") == 2019
    assert _year_of(" ") is None
    assert _year_of("") is None
    assert _year_of("abc") is None


def test_district_benchmark_section():
    yr = datetime.date.today().year
    df = pd.DataFrame([
        {"주용도코드명": "공동주택", "연면적": "10000", "지상층수": "20", "용적률": "300",
         "높이": "60", "사용승인일": f"{yr-5}0101"},
        {"주용도코드명": "공동주택", "연면적": "8000", "지상층수": "10", "용적률": "200",
         "높이": "30", "사용승인일": f"{yr-8}0101"},
    ])
    out = district_to_text(df, total=2, top_uses=10)
    assert "규모 벤치마크" in out
    assert "공동주택" in out
    assert "지상 15층(최대 20)" in out   # 중앙값 (10,20)→15, 최대 20
    assert "용적률 250%" in out          # 중앙 (200,300)→250
    assert "높이 45m" in out             # 중앙 (30,60)→45


def _demo_df():
    return pd.DataFrame([
        {"대지위치": "서울 광진구 자양동 2-2", "철거멸실구분코드명": "철거",
         "철거시작일": "20190301", "철거종료일": "20190430", "철거멸실일": " ",
         "연면적(㎡)": "4697.48", "주용도코드명": "문화및집회시설", "구조코드명": "철골콘크리트구조",
         "천장재함유유무": "0", "단열재함유유무": "1", "지붕재함유유무": "0",
         "보온재함유유무": "0", "바닥재함유유무": "0", "기타함유유무": "0"},
        {"대지위치": "서울 광진구 자양동 9-9", "철거멸실구분코드명": "철거",
         "철거시작일": "20100101", "철거종료일": "20100201", "철거멸실일": " ",
         "연면적(㎡)": "100", "주용도코드명": "단독주택", "구조코드명": "조적조",
         "천장재함유유무": "0", "단열재함유유무": "0", "지붕재함유유무": "0",
         "보온재함유유무": "0", "바닥재함유유무": "0", "기타함유유무": "0"},
    ])


def test_demolitions_sorts_recent_and_flags_asbestos():
    out = demolitions_to_text(_demo_df(), total=2, top=30)
    # 최근(2019)이 먼저
    assert out.index("2-2") < out.index("9-9")
    assert "철거 2019-03-01~2019-04-30" in out
    assert "⚠석면(단열)" in out          # 단열재 함유=1
    assert "연면적 4,697.48㎡" in out
    assert SOURCE in out


def test_demolitions_since_year_filter():
    out = demolitions_to_text(_demo_df(), total=2, since_year=2015, top=30)
    assert "2-2" in out and "9-9" not in out   # 2010건 제외
    assert "2015년↑ 1건" in out


def test_demolitions_future_year_typo_flagged_and_filtered():
    # 미래연도 오타(2108): since_year 필터를 '최근'으로 통과하면 안 되고, 출력 시 의심 표기 (#A11)
    df = pd.concat([_demo_df(), pd.DataFrame([
        {"대지위치": "서울 광진구 자양동 7-7", "철거멸실구분코드명": "철거",
         "철거시작일": "21080607", "철거종료일": " ", "철거멸실일": " ",
         "연면적(㎡)": "50", "주용도코드명": "단독주택", "구조코드명": "조적조",
         "천장재함유유무": "0", "단열재함유유무": "0", "지붕재함유유무": "0",
         "보온재함유유무": "0", "바닥재함유유무": "0", "기타함유유무": "0"},
    ])], ignore_index=True)
    # since_year 지정 시: 2108은 2015년↑ 필터를 통과하지 못한다(연도 오타 의심 처리)
    out = demolitions_to_text(df, total=3, since_year=2015, top=30)
    assert "7-7" not in out and "2108" not in out
    # 전체 조회 시: 표시는 하되 의심 표기 + 최근순 1위를 먹지 않음(강등)
    out_all = demolitions_to_text(df, total=3, top=30)
    assert "(연도 오타 의심)" in out_all
    assert out_all.index("2-2") < out_all.index("7-7")  # 2019건이 2108 오타보다 먼저


def _pipe_df():
    return pd.DataFrame([
        {"대지위치": "자양동 1-1", "건물명": "진행중빌", "건축구분코드": "신축",
         "주용도코드명": "공동주택", "연면적(㎡)": "3000", "세대수(세대)": "19",
         "건축허가일": "20230814", "실제착공일": "20231017", "사용승인일": " "},
        {"대지위치": "자양동 2-2", "건물명": "미착공빌", "건축구분코드": "신축",
         "주용도코드명": "업무시설", "연면적(㎡)": "5000", "세대수(세대)": "0",
         "건축허가일": "20240101", "실제착공일": " ", "사용승인일": " "},
        {"대지위치": "자양동 3-3", "건물명": "완료빌", "건축구분코드": "신축",
         "주용도코드명": "단독주택", "연면적(㎡)": "200", "세대수(세대)": "0",
         "건축허가일": "20200101", "실제착공일": "20200201", "사용승인일": "20201231"},
    ])


def test_pipeline_only_in_progress_and_stages():
    out = pipeline_to_text(_pipe_df(), total=3, top=30)
    assert "진행중(사용승인 전) 2건" in out   # 완료빌 제외
    assert "완료빌" not in out
    # 허가일 최근순: 2024(미착공) 먼저
    assert out.index("미착공빌") < out.index("진행중빌")
    assert "단계: 착공(2023-10-17)" in out
    assert "단계: 미착공" in out
    assert "신축" in out and "19세대" in out


def test_pipeline_since_year_filter():
    out = pipeline_to_text(_pipe_df(), total=3, since_year=2024, top=30)
    assert "미착공빌" in out and "진행중빌" not in out  # 2023허가 제외


def test_pipeline_kind_swap_self_correction_both_ways():
    # swap 자가 보정: 두 컬럼 중 숫자(코드값)가 아닌 쪽을 명칭으로 읽는다.
    # 라이브러리가 swap을 고치든 말든 양방향 모두 '신축'을 표기해야 한다.
    base = {"대지위치": "자양동 1-1", "주용도코드명": "공동주택",
            "건축허가일": f"{datetime.date.today().year}0101", "실제착공일": " ", "사용승인일": " "}
    # (1) swap 있는 환경(PublicDataReader 1.1.x 실측): 명칭이 '건축구분코드'에
    swapped = pd.DataFrame([{**base, "건축구분코드": "신축", "건축구분코드명": "0100"}])
    out = pipeline_to_text(swapped, total=1, top=30)
    assert "신축" in out and "0100" not in out
    # (2) swap 없는 환경(라이브러리 수정 후): 명칭이 '건축구분코드명'에
    fixed = pd.DataFrame([{**base, "건축구분코드명": "신축", "건축구분코드": "0100"}])
    out2 = pipeline_to_text(fixed, total=1, top=30)
    assert "신축" in out2 and "0100" not in out2


def test_permit_kind_helper():
    assert _permit_kind(pd.Series({"건축구분코드": "신축", "건축구분코드명": "0100"})) == "신축"
    assert _permit_kind(pd.Series({"건축구분코드명": "대수선", "건축구분코드": "0300"})) == "대수선"
    assert _permit_kind(pd.Series({"건축구분코드명": "0100", "건축구분코드": "0100"})) is None  # 둘 다 코드값
    assert _permit_kind(pd.Series({"대지위치": "x"})) is None  # 컬럼 자체 없음


def test_pipeline_separates_stale_unstarted_permits():
    # 허가 후 5년 경과 + 미착공 = 장기 미착공(실효 가능성) — 진행중에서 분리 집계 (#A3)
    yr = datetime.date.today().year
    df = pd.DataFrame([
        {"대지위치": "자양동 1-1", "건물명": "최근미착공빌", "건축구분코드": "신축",
         "주용도코드명": "업무시설", "건축허가일": f"{yr}0102", "실제착공일": " ", "사용승인일": " "},
        {"대지위치": "자양동 2-2", "건물명": "장기미착공빌", "건축구분코드": "신축",
         "주용도코드명": "업무시설", "건축허가일": f"{yr - 20}0101", "실제착공일": " ", "사용승인일": " "},
        {"대지위치": "자양동 3-3", "건물명": "장기공사중빌", "건축구분코드": "신축",
         "주용도코드명": "업무시설", "건축허가일": f"{yr - 20}0101", "실제착공일": f"{yr - 19}0101", "사용승인일": " "},
    ])
    out = pipeline_to_text(df, total=3, top=30)
    assert "진행중(사용승인 전) 2건" in out          # 장기미착공빌 분리, 착공한 건은 잔류
    assert "장기 미착공" in out and "실효 가능성" in out and "1건" in out
    assert "장기미착공빌" not in out                 # 목록에서 제외
    assert "최근미착공빌" in out and "장기공사중빌" in out
    assert "허가가 실효되었을 수 있음" in out         # 해석 주의 경고


def test_pipeline_stale_warning_always_present():
    out = pipeline_to_text(_pipe_df(), total=3, top=30)
    assert "허가가 실효되었을 수 있음" in out


def test_df_to_text_empty_and_source():
    assert "0건" in df_to_text(pd.DataFrame())
    out = df_to_text(pd.DataFrame([{"a": 1}, {"a": 2}]), max_rows=1)
    assert "상위 1건" in out and SOURCE in out


# ---- 컬럼 프루닝 (토큰 최적화) ----

def _prune_df():
    return pd.DataFrame([
        {"시군구코드": "11215", "법정동코드": "10500", "순번": "1", "건물명": "A",
         "특수지명": "", "구조코드": "43", "구조코드명": "철근콘크리트구조",
         "건축구분코드명": "0100", "건축구분코드": "신축", "지하층수": "0"},
        {"시군구코드": "11215", "법정동코드": "10500", "순번": "2", "건물명": "B",
         "특수지명": "nan", "구조코드": "21", "구조코드명": "벽돌구조",
         "건축구분코드명": "0600", "건축구분코드": "대수선", "지하층수": "1"},
    ])


def test_prune_drops_empty_echo_and_code_twins():
    pruned, n = _prune_columns(_prune_df())
    assert "특수지명" not in pruned.columns                 # 전부 빈값
    for col in ("시군구코드", "법정동코드", "순번"):        # 조회 인자/행번호 에코
        assert col not in pruned.columns
    assert "구조코드" not in pruned.columns                 # 코드값 쪽 제거
    assert "구조코드명" in pruned.columns                   # 한글 명칭 유지
    assert n == 6


def test_prune_handles_swapped_code_columns():
    # swap 환경(명칭이 '건축구분코드'에): 값 기준이므로 코드값 쪽('건축구분코드명')이 제거된다
    pruned, _ = _prune_columns(_prune_df())
    assert "건축구분코드명" not in pruned.columns
    assert "건축구분코드" in pruned.columns


def test_prune_keeps_zero_columns():
    # '0'은 미기재가 아니라 의미값일 수 있음(지하층수 0 등) — 제거하지 않는다
    pruned, _ = _prune_columns(_prune_df())
    assert "지하층수" in pruned.columns


def test_df_to_text_prune_note_and_opt_out():
    out = df_to_text(_prune_df())
    assert "컬럼 6개 생략" in out and "특수지명" not in out
    out_raw = df_to_text(_prune_df(), prune=False)
    assert "특수지명" in out_raw and "생략" not in out_raw


# ---- parcel_history (필지 연혁 타임라인) ----

def test_parcel_history_merges_and_sorts_sources():
    today = datetime.date(2026, 6, 12)
    permits = pd.DataFrame([
        {"관리허가대장PK": "N1", "건축구분코드": "신축", "주용도코드명": "업무시설",
         "건축허가일": "20180418", "실제착공일": "20190926", "사용승인일": "20221007",
         "연면적(㎡)": "28515.35", "호수(호)": "366", "건물명": "자이엘라"},
        {"관리허가대장PK": "T1", "건축허가일": "20200630", "연면적(㎡)": "36"},  # 가설 PK → 가설 이벤트로
        {"관리허가대장PK": "N2"},  # 일자·구분·면적 전무 — 노이즈 제외
    ])
    demos = pd.DataFrame([
        {"철거멸실구분코드명": "철거", "철거시작일": "20190301", "철거종료일": "20190430",
         "주용도코드명": "문화및집회시설", "구조코드명": "철골콘크리트구조",
         "연면적(㎡)": "4697.48", "천장재함유유무": "1"},
    ])
    temps = pd.DataFrame([
        {"관리허가대장PK": "T1", "구조코드명": "컨테이너조", "전체연면적(㎡)": "36",
         "가설건축물존치만료일": "20220820"},
    ])
    out = parcel_history_to_text(permits, demos, temps, bun="2", ji="2", today=today)
    assert "[필지 연혁] 2-2" in out
    assert "신축" in out and "착공 2019-09-26 → 사용승인 2022-10-07" in out
    assert "철거멸실" in out and "⚠석면(천장)" in out
    # 가설: 기본개요의 허가일이 합쳐지고, 기본개요 쪽 중복 행은 미표시
    assert "2020-06-30 허가 — 가설건축물" in out
    assert "존치만료 2022-08-20" in out and "경과" in out
    assert "빈 행 1건 제외" in out
    # 오래된 순: 신축허가(2018) → 철거(2019) → 가설(2020)
    assert out.index("2018-04-18") < out.index("2019-03-01") < out.index("2020-06-30")
    assert SOURCE in out


def test_parcel_history_all_empty_is_not_found():
    out = parcel_history_to_text(pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), bun="9")
    assert "[NOT_FOUND]" in out


# ---- temp_buildings (가설건축물 존치 현황) ----

def _temp_df():
    return pd.DataFrame([
        # 만료 경과 — 같은 PK 2행(동 2개)은 1건으로 묶임
        {"관리허가대장PK": "P1", "대지위치": "자양동 2-2번지", "구조코드명": "컨테이너조",
         "주용도코드명": "가설건축물", "전체연면적(㎡)": "171", "가설건축물존치만료일": "20220820"},
        {"관리허가대장PK": "P1", "대지위치": "자양동 2-2번지", "구조코드명": "컨테이너조",
         "주용도코드명": "가설건축물", "전체연면적(㎡)": "171", "가설건축물존치만료일": "20220820"},
        # 만료임박 (D-50)
        {"관리허가대장PK": "P2", "대지위치": "자양동 3-1번지", "구조코드명": "컨테이너조",
         "주용도코드명": "가설건축물", "전체연면적(㎡)": "36", "가설건축물존치만료일": "20260801"},
        # 유효
        {"관리허가대장PK": "P3", "대지위치": "자양동 4-1번지", "구조코드명": "컨테이너조",
         "주용도코드명": "가설건축물", "전체연면적(㎡)": "20", "가설건축물존치만료일": "20280101"},
        # 만료일 미상
        {"관리허가대장PK": "P4", "대지위치": "자양동 5-1번지", "구조코드명": "컨테이너조",
         "주용도코드명": "가설건축물", "전체연면적(㎡)": "10", "가설건축물존치만료일": " "},
    ])


def test_temp_buildings_classifies_by_expiry():
    out = temp_buildings_to_text(_temp_df(), total=5, today=datetime.date(2026, 6, 12))
    assert "PK 기준 4건" in out                            # 5행 → PK 4건
    assert "존치만료 경과 1건" in out
    assert "만료임박(180일 이내) 1건" in out
    assert "유효 1건" in out and "미상 1건" in out
    assert "2개 동" in out                                  # P1 동 2개 묶음
    assert "D-50" in out                                    # 2026-08-01 임박
    # 만료 경과가 임박보다 먼저
    assert out.index("2-2번지") < out.index("3-1번지")
    # 유효·미상은 우선 점검 목록에 미표시
    assert "4-1번지" not in out and "5-1번지" not in out
    assert "연장 신고가 대장에 지연 반영" in out            # 해석 주의
    assert SOURCE in out


def test_temp_buildings_no_expired_message():
    df = _temp_df().iloc[[3]]  # 유효 건만
    out = temp_buildings_to_text(df, total=1, today=datetime.date(2026, 6, 12))
    assert "만료 경과·임박 건 없음" in out
