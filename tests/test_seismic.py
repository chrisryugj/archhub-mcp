"""seismic_check — 내진설계 의무화 연혁 규칙·포맷터 단위테스트 (외부 API 비의존).

규칙: 사용승인일 시점의 의무 기준에 해당하지 않던 건물 = "미적용 추정".
경계연도(1988/2005/2015/2017.12) 전후로 판정이 바뀌는지 고정한다.
"""

import pandas as pd

from archhub.formatting import (
    seismic_status, seismic_to_text, _vulnerable_struct, SOURCE,
)


# ---- 규칙 함수: 경계연도 케이스 ----

def test_pre_1988_always_unapplied():
    # 1988-03 이전: 내진 의무 자체가 없던 시기 — 규모 무관 미적용 추정
    status, basis = seismic_status("19870101", 20, 50000)
    assert status == "미적용 추정"
    assert "1988" in basis and "이전" in basis


def test_1988_rule_boundary():
    # 1988 도입: 6층↑ 또는 10만㎡↑
    assert seismic_status("19880301", 6, 500)[0] == "의무 적용 추정"      # 6층
    assert seismic_status("19880301", 5, 100_000)[0] == "의무 적용 추정"  # 10만㎡
    assert seismic_status("19900101", 5, 5_000)[0] == "미적용 추정"       # 둘 다 미달
    assert seismic_status("19880228", 6, 500)[0] == "미적용 추정"         # 시행 직전 승인


def test_2005_rule_boundary():
    # 2005: 3층↑ 또는 1,000㎡↑
    assert seismic_status("20050101", 3, 200)[0] == "의무 적용 추정"
    assert seismic_status("20050101", 2, 1_000)[0] == "의무 적용 추정"
    assert seismic_status("20050101", 2, 999)[0] == "미적용 추정"
    # 2005 직전(2004): 1995 기준(6층/1만㎡) 적용 → 3층·1,000㎡는 미적용
    assert seismic_status("20041231", 3, 1_000)[0] == "미적용 추정"


def test_2015_rule_boundary():
    # 2015: 2층↑ 또는 500㎡↑
    assert seismic_status("20150101", 2, 100)[0] == "의무 적용 추정"
    assert seismic_status("20150101", 1, 500)[0] == "의무 적용 추정"
    assert seismic_status("20150101", 1, 499)[0] == "미적용 추정"
    # 2015 직전(2014): 2005 기준(3층/1,000㎡) 적용 → 2층·600㎡는 미적용
    assert seismic_status("20141231", 2, 600)[0] == "미적용 추정"


def test_2017_12_rule_boundary():
    # 2017.12: 2층↑(목구조 3층↑) 또는 200㎡↑ + 모든 주택
    assert seismic_status("20171201", 1, 200)[0] == "의무 적용 추정"
    assert seismic_status("20171201", 1, 150)[0] == "미적용 추정"           # 소규모 비주택
    # 모든 주택은 규모 무관 의무
    status, basis = seismic_status("20171201", 1, 80, use="단독주택")
    assert status == "의무 적용 추정" and "주택" in basis
    # 목구조는 3층부터 (2층 목구조 150㎡ = 미적용)
    assert seismic_status("20180601", 2, 150, struct="목구조")[0] == "미적용 추정"
    assert seismic_status("20180601", 3, 150, struct="목구조")[0] == "의무 적용 추정"
    # 2017.12 직전(2017-11): 2015 기준(2층/500㎡) 적용 → 1층 250㎡ 비주택은 미적용
    assert seismic_status("20171130", 1, 250)[0] == "미적용 추정"


def test_seismic_status_unknown_inputs():
    assert seismic_status("", 5, 1000)[0] == "판정 불가"          # 승인일 미상
    assert seismic_status("abc", 5, 1000)[0] == "판정 불가"
    assert seismic_status("20200101", "", "")[0] == "판정 불가"   # 층수·연면적 모두 미상
    # 연도만 있어도(YYYY) 판정 가능 — 1월 1일로 간주
    assert seismic_status("1980", 10, 9999)[0] == "미적용 추정"


def test_vulnerable_struct_keywords():
    assert _vulnerable_struct("조적조")
    assert _vulnerable_struct("벽돌구조")
    assert _vulnerable_struct("시멘트블럭조")
    assert not _vulnerable_struct("철근콘크리트구조")
    assert not _vulnerable_struct("")


# ---- 포맷터 ----

def _seismic_df():
    return pd.DataFrame([
        # 1985년 승인 조적조 4층 — 미적용 추정(1988 이전) + 취약구조
        {"대지위치": "자양동 1-1", "건물명": "조적빌", "구조코드명": "조적조",
         "주용도코드명": "제2종근린생활시설", "사용승인일": "19850301", "지상층수": "4", "연면적": "800"},
        # 1990년 승인 RC 5층 5,000㎡ — 1988 기준(6층/10만㎡) 미달 → 미적용 추정
        {"대지위치": "자양동 2-2", "건물명": "RC빌", "구조코드명": "철근콘크리트구조",
         "주용도코드명": "업무시설", "사용승인일": "19900601", "지상층수": "5", "연면적": "5000"},
        # 2020년 승인 3층 — 2017.12 기준 해당 → 의무 적용 추정
        {"대지위치": "자양동 3-3", "건물명": "신축빌", "구조코드명": "철근콘크리트구조",
         "주용도코드명": "업무시설", "사용승인일": "20200101", "지상층수": "3", "연면적": "900"},
        # 승인일 미상 → 판정 불가
        {"대지위치": "자양동 4-4", "건물명": "미상빌", "구조코드명": "철근콘크리트구조",
         "주용도코드명": "업무시설", "사용승인일": " ", "지상층수": "2", "연면적": "300"},
    ])


def test_seismic_to_text_summary_and_priority():
    out = seismic_to_text(_seismic_df(), total=4, min_floors=3, max_buildings=30)
    assert "미적용 추정 2건 / 전체 4동" in out
    assert "의무 적용 추정 1건" in out and "판정 불가 1건" in out
    assert "1988년 의무화 이전 승인 1건" in out
    # 우선순위: 취약구조(조적조 4층)가 더 높은 층수(RC 5층)보다 먼저
    assert out.index("조적빌") < out.index("RC빌")
    assert "⚠취약구조" in out
    assert "근거:" in out and "승인 1985-03-01" in out
    # 의무 적용 추정 건은 점검 후보 목록에 없다
    assert "신축빌" not in out
    assert SOURCE in out


def test_seismic_to_text_min_floors_filters_list_not_summary():
    # min_floors=5: 조적빌(4층)은 목록에서 빠지지만 요약 집계엔 포함
    out = seismic_to_text(_seismic_df(), total=4, min_floors=5, max_buildings=30)
    assert "미적용 추정 2건" in out      # 요약은 그대로
    assert "조적빌" not in out           # 목록에서만 제외
    assert "RC빌" in out


def test_seismic_to_text_disclaimer():
    # 면책 필수: 대장 기재 기준 추정 — 실제 내진성능은 구조안전진단으로만 확인
    out = seismic_to_text(_seismic_df(), total=4)
    assert "구조안전진단" in out
    assert "내진보강 이력은 대장에 미반영" in out


def test_seismic_to_text_truncation():
    out = seismic_to_text(_seismic_df(), total=4, min_floors=3, max_buildings=1)
    assert "상위 1건 표시" in out
    assert "조적빌" in out and "RC빌" not in out  # 취약구조 우선 1건만
