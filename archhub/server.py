"""건축HUB MCP 서버.

stdio 모드(로컬 Claude Desktop/Code)와 streamable-http 모드(fly.io remote 커넥터)를
모두 지원한다. 공용 서비스키는 환경변수 ARCHHUB_SERVICE_KEY로 주입한다.
"""

import argparse
import datetime
import os
from pathlib import Path

import pandas as pd
from fastmcp import FastMCP
from starlette.responses import JSONResponse

from . import __version__
from .client import ArchHubClient, KINDS, LEDGER_TYPES, PERMIT_TYPES, HOUSING_TYPES, DAILY_CALL_CAP
from .errors import not_found, format_error
from .formatting import (
    df_to_text, profile_to_text, district_to_text, floors_to_text,
    price_history_to_text, demolitions_to_text, pipeline_to_text, _date, _age_years,
)


def _load_env_local() -> None:
    """.env.local(KEY=VALUE)을 os.environ에 주입한다(이미 설정된 키는 보존).

    README가 안내하는 .env.local을 실제로 로드한다. python-dotenv 의존 없이 stdlib로
    처리(로컬 편의 한정 — 운영은 fly secrets/환경변수 사용)."""
    for base in (Path.cwd(), Path(__file__).resolve().parent.parent):
        path = base / ".env.local"
        if not path.exists():
            continue
        try:
            for line in path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, _, v = line.partition("=")
                k, v = k.strip(), v.strip().strip('"').strip("'")
                if k and k not in os.environ:
                    os.environ[k] = v
        except OSError:
            pass
        return


_load_env_local()

SERVICE_KEY = os.environ.get("ARCHHUB_SERVICE_KEY", "").strip()
KEY_EXPIRES = os.environ.get("ARCHHUB_KEY_EXPIRES", "").strip()  # 공용키 만료일 YYYY-MM-DD(선택)
MCP_TOKEN = os.environ.get("ARCHHUB_MCP_TOKEN", "").strip()      # 설정 시 remote 접근에 Bearer 토큰 요구
client = ArchHubClient(SERVICE_KEY)


def _build_auth():
    """ARCHHUB_MCP_TOKEN이 설정되면 Bearer 토큰 인증을 켠다(공개 remote의 공용키 보호).

    미설정이면 None — 무인증 유지(로컬 stdio 등 신뢰 환경 호환). fly 배포 시
    `fly secrets set ARCHHUB_MCP_TOKEN=...` 로 켜고, 허가된 사용자에게만 토큰을 공유한다."""
    if not MCP_TOKEN:
        return None
    from fastmcp.server.auth.providers.jwt import StaticTokenVerifier
    return StaticTokenVerifier(tokens={MCP_TOKEN: {"client_id": "archhub"}})


def _key_expiry_days():
    """공용키 만료까지 남은 일수. ARCHHUB_KEY_EXPIRES 미설정/형식오류면 None."""
    if not KEY_EXPIRES:
        return None
    try:
        exp = datetime.date.fromisoformat(KEY_EXPIRES)
    except ValueError:
        return None
    return (exp - datetime.date.today()).days


def _fetch_zoning(sigungu_code: str, bdong_code: str, bun: str, ji: str):
    """필지의 용도지역·지구·구역(대표) 요약. 실패/없으면 None (profile 부가정보라 조용히 생략)."""
    try:
        df, _ = client.query("ledger", "지역지구구역", sigungu_code, bdong_code,
                             bun=bun, ji=ji, num_rows=20)
    except Exception:
        return None
    if len(df) == 0 or "지역지구구역코드명" not in df.columns:
        return None
    src = df
    if "대표여부" in df.columns:
        rep = df[df["대표여부"].astype(str).str.strip() == "1"]
        if len(rep):
            src = rep
    names = list(dict.fromkeys(src["지역지구구역코드명"].astype(str).str.strip()))
    names = [n for n in names if n and n.lower() != "nan"]
    return " · ".join(names) or None

mcp = FastMCP(
    name="archhub",
    instructions=(
        "국토교통부 건축HUB(공공데이터포털) 건축물대장·건축인허가·주택인허가 조회 서버. "
        "주소는 먼저 find_region으로 sigungu_code/bdong_code를 얻은 뒤 다른 도구에 넘긴다. "
        "데이터는 모두 공식 API 실측값이며, 결과가 없으면 추측하지 말고 '데이터 없음'을 보고한다."
    ),
    auth=_build_auth(),
)


# ---- 도구 ----


@mcp.tool
def find_region(keyword: str, limit: int = 20) -> str:
    """주소 키워드로 시군구코드/법정동코드를 조회한다.

    예: "광진구 자양동" → 해당 동의 sigungu_code(5자리)·bdong_code(5자리).
    여기서 얻은 코드를 building_ledger / building_permit / housing_permit /
    old_buildings 도구의 sigungu_code·bdong_code 인자로 사용한다.

    Args:
        keyword: 공백으로 구분된 주소 키워드(시/군/구/동). 모두 포함하는 행을 검색.
        limit: 최대 반환 행 수.
    """
    try:
        res = client.find_region(keyword)
    except Exception as e:
        return format_error(e, "find_region")
    if len(res) == 0:
        return not_found(f"'{keyword}' 에 해당하는 지역 없음", ["시/구/동 이름 일부로 다시 검색"])
    cols = ["시도명", "시군구명", "읍면동명", "동리명", "법정동코드", "sigungu_code", "bdong_code"]
    return df_to_text(res[cols], max_rows=limit, note="아래 sigungu_code/bdong_code를 다른 도구의 인자로 사용하세요.")


def _query(kind: str, ctx: str, type_name, sigungu_code, bdong_code, bun, ji, max_rows, page) -> str:
    try:
        df, total = client.query(
            kind, type_name, sigungu_code, bdong_code,
            bun=bun, ji=ji, num_rows=max_rows, page_no=page,
        )
    except Exception as e:
        return format_error(e, ctx)
    if len(df) == 0:
        return not_found(
            f"{ctx} '{type_name}' 결과 없음 (sigungu={sigungu_code}, bdong={bdong_code})",
            ["find_region으로 코드 재확인", "bun/ji 없이 동 전체로 조회", "조회 유형(type_name) 변경"],
        )
    note = f"유형={type_name} · 전체 {total}건 · page={page}"
    return df_to_text(df, max_rows=max_rows, note=note)


@mcp.tool
def building_ledger(
    type_name: str,
    sigungu_code: str,
    bdong_code: str,
    bun: str = "",
    ji: str = "",
    max_rows: int = 50,
    page: int = 1,
) -> str:
    """건축물대장 정보를 조회한다 (국토부 건축HUB).

    Args:
        type_name: 조회 유형. 다음 중 하나 —
            기본개요|총괄표제부|표제부|층별개요|부속지번|전유공용면적|오수정화시설|주택가격|전유부|지역지구구역
        sigungu_code: 시군구 5자리 코드 (find_region으로 조회).
        bdong_code: 읍면동 5자리 코드.
        bun: 번지 본번(생략 시 동 전체). 큰 동은 번지 지정이 빠름.
        ji: 번지 부번.
        max_rows: 한 페이지 반환 행 수(최대 100; 더 필요하면 page를 증가).
        page: 페이지 번호(동 전체가 max_rows보다 많을 때 증가).
    """
    return _query("ledger", "건축물대장", type_name, sigungu_code, bdong_code, bun, ji, max_rows, page)


@mcp.tool
def building_permit(
    type_name: str,
    sigungu_code: str,
    bdong_code: str,
    bun: str = "",
    ji: str = "",
    max_rows: int = 50,
    page: int = 1,
) -> str:
    """건축인허가 정보를 조회한다 (국토부 건축HUB).

    Args:
        type_name: 조회 유형. 다음 중 하나 —
            기본개요|동별개요|층별개요|호별개요|대수선|공작물관리대장|철거멸실관리대장|
            가설건축물|오수정화시설|주차장|부설주차장|전유공용면적|호별전유공용면적|
            지역지구구역|도로명대장|대지위치|주택유형
        sigungu_code: 시군구 5자리 코드.
        bdong_code: 읍면동 5자리 코드.
        bun: 번지 본번.
        ji: 번지 부번.
        max_rows: 한 페이지 반환 행 수(최대 100; 더 필요하면 page를 증가).
        page: 페이지 번호.
    """
    return _query("permit", "건축인허가", type_name, sigungu_code, bdong_code, bun, ji, max_rows, page)


@mcp.tool
def housing_permit(
    type_name: str,
    sigungu_code: str,
    bdong_code: str,
    bun: str = "",
    ji: str = "",
    max_rows: int = 50,
    page: int = 1,
) -> str:
    """주택인허가 정보를 조회한다 (국토부 건축HUB).

    Args:
        type_name: 조회 유형. 다음 중 하나 —
            기본개요|동별개요|층별개요|호별개요|부대시설|오수정화시설|주차장|부설주차장|
            전유공용면적|행위호전유공용면적|행위개요|관리공동형별개요|관리공동부대복리시설|
            지역지구구역|복리분양시설|대지위치
        sigungu_code: 시군구 5자리 코드.
        bdong_code: 읍면동 5자리 코드.
        bun: 번지 본번.
        ji: 번지 부번.
        max_rows: 한 페이지 반환 행 수(최대 100; 더 필요하면 page를 증가).
        page: 페이지 번호.
    """
    return _query("housing", "주택인허가", type_name, sigungu_code, bdong_code, bun, ji, max_rows, page)


@mcp.tool
def building_profile(
    sigungu_code: str,
    bdong_code: str,
    bun: str,
    ji: str = "",
    max_buildings: int = 5,
) -> str:
    """한 필지(번지)의 건축물 핵심 스펙 + 용도지역을 종합 카드로 한 번에 조회한다.

    표제부와 지역지구구역을 호출해 ① 용도지역·지구(법적 규제) ② 동별 주용도·구조·
    규모(층수/높이/연면적/대지면적) ③ 건폐율·용적률(미기재 시 면적으로 계산) ④ 세대/호수·
    주차·사용승인일·내진·에너지효율을 카드로 묶어준다. type_name을 바꿔 여러 번 호출할
    필요 없이 건물 한 채의 전반과 대지 규제를 함께 파악하는, 가장 먼저 쓰는 도구다.
    (건축사·시공·중개·감정평가 실무용. 규모검토·대지분석의 출발점)

    Args:
        sigungu_code: 시군구 5자리 코드 (find_region으로 조회).
        bdong_code: 읍면동 5자리 코드.
        bun: 번지 본번. **필수** (동 전체는 무거우므로 필지를 지정).
        ji: 번지 부번(생략 가능).
        max_buildings: 한 필지에 여러 동이 있을 때 카드로 표시할 최대 동 수.
    """
    if not str(bun).strip():
        return not_found(
            "building_profile은 번지(bun)가 필요합니다. 동 전체 조회는 building_ledger를 쓰세요.",
            ["find_region으로 코드 확인 후 bun(본번) 지정"],
        )
    try:
        df, total = client.query(
            "ledger", "표제부", sigungu_code, bdong_code,
            bun=bun, ji=ji, num_rows=100,
        )
    except Exception as e:
        return format_error(e, "building_profile")
    if len(df) == 0:
        return not_found(
            f"건축물대장 표제부 없음 (sigungu={sigungu_code}, bdong={bdong_code}, bun={bun}, ji={ji})",
            ["find_region으로 코드 재확인", "ji(부번) 조정", "건축물대장이 없는 필지일 수 있음"],
        )
    zoning = _fetch_zoning(sigungu_code, bdong_code, bun, ji)
    return profile_to_text(df, total, max_buildings, zoning=zoning)


@mcp.tool
def old_buildings(
    sigungu_code: str,
    bdong_code: str,
    min_age_years: int = 30,
    top: int = 30,
) -> str:
    """특정 법정동의 노후 건축물을 사용승인일 기준으로 조회한다.

    건축물대장 표제부 전체를 받아 사용승인 경과연수를 계산하고, min_age_years 이상인
    건물을 경과연수 내림차순으로 정렬해 반환한다. (안전점검·정비사업 대상 선별용)
    동 전체를 받으므로 응답이 다소 느릴 수 있다.

    Args:
        sigungu_code: 시군구 5자리 코드 (find_region으로 조회).
        bdong_code: 읍면동 5자리 코드.
        min_age_years: 노후 판정 기준 경과연수(년). 기본 30.
        top: 반환 최대 건수.
    """
    try:
        df, total = client.query("ledger", "표제부", sigungu_code, bdong_code, fetch_all=True)
    except Exception as e:
        return format_error(e, "old_buildings")
    if len(df) == 0:
        return not_found(f"표제부 데이터 없음 (sigungu={sigungu_code}, bdong={bdong_code})")

    collected = len(df)
    trunc = f" (응답 한도로 {collected}건만 수집)" if collected < total else ""

    col = "사용승인일"
    if col not in df.columns:
        return format_error(Exception(f"표제부에 '{col}' 컬럼 없음. 실제 컬럼: {list(df.columns)}"), "old_buildings")

    d = df.copy()
    d[col] = d[col].astype(str).str.strip()
    d["경과연수"] = pd.to_numeric(d[col].map(_age_years), errors="coerce")  # 월·일 반영 만 경과연수
    d = d.dropna(subset=["경과연수"])
    d["경과연수"] = d["경과연수"].astype(int)
    old = d[d["경과연수"] >= min_age_years].sort_values("경과연수", ascending=False)
    if len(old) == 0:
        return not_found(f"경과 {min_age_years}년 이상 건축물 없음 (표제부 전체 {total}건)")

    candidate = ["건물명", "도로명대지위치", "대지위치", "주용도코드명",
                 "사용승인일", "경과연수", "연면적", "지상층수", "세대수"]
    cols = [c for c in candidate if c in old.columns]
    out = old[cols].copy()
    out["사용승인일"] = out["사용승인일"].map(lambda v: _date(v) or v)  # YYYYMMDD → YYYY-MM-DD
    note = f"표제부 {total}건{trunc} 중 경과 {min_age_years}년↑ {len(old)}건 (경과연수 내림차순)"
    return df_to_text(out, max_rows=top, note=note)


@mcp.tool
def district_stats(
    sigungu_code: str,
    bdong_code: str,
    min_age_years: int = 30,
    top_uses: int = 10,
) -> str:
    """법정동 단위 건축물 현황을 집계 통계로 조회한다 (동 전체 표제부 기반).

    건축물대장 표제부 전체를 받아 ① 총괄(동수·총연면적·평균층수·평균경과연수)
    ② 주용도별 분포 ③ 사용승인 연대별 분포 ④ 노후도 구간별 분포를 한 번에 집계한다.
    개별 건물이 아니라 '동 전체 그림'이 필요할 때 쓴다. (도시계획·정비사업·지역분석용)
    동 전체를 받으므로 응답이 다소 느릴 수 있다.

    Args:
        sigungu_code: 시군구 5자리 코드 (find_region으로 조회).
        bdong_code: 읍면동 5자리 코드.
        min_age_years: 노후 합계 판정 기준 경과연수(년). 기본 30.
        top_uses: 주용도별 분포에서 표시할 상위 용도 수.
    """
    try:
        df, total = client.query("ledger", "표제부", sigungu_code, bdong_code, fetch_all=True)
    except Exception as e:
        return format_error(e, "district_stats")
    if len(df) == 0:
        return not_found(
            f"표제부 데이터 없음 (sigungu={sigungu_code}, bdong={bdong_code})",
            ["find_region으로 코드 재확인"],
        )
    collected = len(df)
    trunc = f" (응답 한도로 {collected}건만 집계)" if collected < total else ""
    return district_to_text(df, total, trunc, min_age_years, top_uses)


@mcp.tool
def building_floors(
    sigungu_code: str,
    bdong_code: str,
    bun: str,
    ji: str = "",
    max_floors: int = 60,
) -> str:
    """한 필지 건물의 층별 구성(각 층 용도·면적)을 스택으로 조회한다.

    건축물대장 층별개요를 호출해 옥탑→지상→지하 순으로 각 층의 주용도와 면적을 쌓아
    보여준다. 한 층에 여러 용도가 있으면 면적을 합산해 나열한다. "각 층에 뭐가 있나"가
    필요한 리모델링·용도변경·임대구성·피난/소방 검토에 쓴다. (건축사·시공·중개)

    Args:
        sigungu_code: 시군구 5자리 코드 (find_region으로 조회).
        bdong_code: 읍면동 5자리 코드.
        bun: 번지 본번. **필수** (필지 단위 조회).
        ji: 번지 부번(생략 가능).
        max_floors: 표시할 최대 층 수.
    """
    if not str(bun).strip():
        return not_found(
            "building_floors는 번지(bun)가 필요합니다.",
            ["find_region으로 코드 확인 후 bun(본번) 지정"],
        )
    try:
        df, total = client.query(
            "ledger", "층별개요", sigungu_code, bdong_code,
            bun=bun, ji=ji, num_rows=100,
        )
    except Exception as e:
        return format_error(e, "building_floors")
    if len(df) == 0:
        return not_found(
            f"층별개요 없음 (sigungu={sigungu_code}, bdong={bdong_code}, bun={bun}, ji={ji})",
            ["find_region으로 코드 재확인", "ji(부번) 조정", "building_profile로 동 단위 먼저 확인"],
        )
    return floors_to_text(df, total, max_floors)


@mcp.tool
def price_history(
    sigungu_code: str,
    bdong_code: str,
    bun: str,
    ji: str = "",
    top_units: int = 10,
) -> str:
    """한 필지의 공시가격(주택가격) 연도별 추이를 호별로 조회한다.

    건축물대장 주택가격을 받아 호(관리건축물대장PK)별로 stdDay(기준일) 순 시계열을 만들고
    최신 공시가·최초→최신 추이·총증감률·연평균상승률(CAGR)을 요약한다. 집합건물은
    호×연도라 행이 많으므로 필지(bun) 단위로 수집한다. (감정평가·중개·자산분석용.
    공시가격은 공개 API값이며 소유자 정보는 포함하지 않는다.)

    Args:
        sigungu_code: 시군구 5자리 코드 (find_region으로 조회).
        bdong_code: 읍면동 5자리 코드.
        bun: 번지 본번. **필수** (동 전체는 무거우므로 필지를 지정).
        ji: 번지 부번(생략 가능).
        top_units: 최신 공시가 상위 몇 호를 표시할지.
    """
    if not str(bun).strip():
        return not_found(
            "price_history는 번지(bun)가 필요합니다. (집합건물은 호×연도라 동 전체가 무거움)",
            ["find_region으로 코드 확인 후 bun(본번) 지정"],
        )
    try:
        df, total = client.query(
            "ledger", "주택가격", sigungu_code, bdong_code,
            bun=bun, ji=ji, fetch_all=True,
        )
    except Exception as e:
        return format_error(e, "price_history")
    if len(df) == 0:
        return not_found(
            f"주택가격(공시가격) 없음 (sigungu={sigungu_code}, bdong={bdong_code}, bun={bun}, ji={ji})",
            ["find_region으로 코드 재확인", "ji(부번) 조정", "공시가격이 없는 필지(비주거 등)일 수 있음"],
        )
    return price_history_to_text(df, total, top_units, bun=bun, ji=ji)


@mcp.tool
def demolitions(
    sigungu_code: str,
    bdong_code: str,
    since_year: int = 0,
    top: int = 30,
) -> str:
    """법정동의 철거멸실 현황을 최근 철거순으로 조회한다 (석면 함유 포함).

    건축인허가 철거멸실관리대장 전체를 받아 철거시작일/멸실일 기준 최근순으로 정렬하고,
    연면적·용도·구조 + 석면(천장/단열/지붕/보온/바닥/기타) 함유 부위를 ⚠로 요약한다.
    석면은 철거 안전·비용에 직결된다. 개발·멸실 신호 파악용. (디벨로퍼·철거업체·공무원)
    동 전체를 받으므로 응답이 다소 느릴 수 있다.

    Args:
        sigungu_code: 시군구 5자리 코드 (find_region으로 조회).
        bdong_code: 읍면동 5자리 코드.
        since_year: 이 연도 이후(철거시작/멸실 기준)만. 0이면 전체.
        top: 반환 최대 건수.
    """
    try:
        df, total = client.query("permit", "철거멸실관리대장", sigungu_code, bdong_code, fetch_all=True)
    except Exception as e:
        return format_error(e, "demolitions")
    if len(df) == 0:
        return not_found(
            f"철거멸실 데이터 없음 (sigungu={sigungu_code}, bdong={bdong_code})",
            ["find_region으로 코드 재확인"],
        )
    collected = len(df)
    trunc = f" (응답 한도로 {collected}건만 수집)" if collected < total else ""
    return demolitions_to_text(df, total, trunc, since_year or None, top)


@mcp.tool
def permits_pipeline(
    sigungu_code: str,
    bdong_code: str,
    since_year: int = 0,
    top: int = 30,
) -> str:
    """법정동의 건축 인허가 파이프라인(사용승인 전 진행중 건)을 조회한다.

    건축인허가 기본개요 전체를 받아 허가는 났으나 사용승인 전인 '진행중' 건만 추려
    건축허가일 최근순으로 정렬한다. 실제착공일 유무로 착공/미착공 단계를 구분해 신규
    공급 파이프라인을 파악한다. (디벨로퍼·공무원용) 동 전체를 받아 다소 느릴 수 있다.

    Args:
        sigungu_code: 시군구 5자리 코드 (find_region으로 조회).
        bdong_code: 읍면동 5자리 코드.
        since_year: 이 연도 이후(건축허가일 기준)만. 0이면 전체.
        top: 반환 최대 건수.
    """
    try:
        df, total = client.query("permit", "기본개요", sigungu_code, bdong_code, fetch_all=True)
    except Exception as e:
        return format_error(e, "permits_pipeline")
    if len(df) == 0:
        return not_found(
            f"건축인허가 기본개요 없음 (sigungu={sigungu_code}, bdong={bdong_code})",
            ["find_region으로 코드 재확인"],
        )
    collected = len(df)
    trunc = f" (응답 한도로 {collected}건만 수집)" if collected < total else ""
    return pipeline_to_text(df, total, trunc, since_year or None, top)


# ---- HTTP 라우트 ----


@mcp.custom_route("/health", methods=["GET"])
async def health(request):
    info = {
        "status": "ok",
        "version": __version__,
        "key_loaded": bool(SERVICE_KEY),
        "auth_required": bool(MCP_TOKEN),       # Bearer 토큰 인증 활성 여부
        "api_calls": client.api_calls,          # 프로세스 생존 동안 data.go.kr 호출수(공용키 한도 관측용)
        "calls_today": client._calls_today,     # 오늘 호출수(일일 캡 관측)
        "daily_cap": DAILY_CALL_CAP or None,    # 일일 호출 캡(0/미설정이면 null)
    }
    days = _key_expiry_days()
    if days is not None:
        info["key_expires"] = KEY_EXPIRES
        info["key_expires_in_days"] = days
        info["key_expiry_warning"] = days <= 30  # 만료 임박 경고
    return JSONResponse(info)


@mcp.custom_route("/", methods=["GET"])
async def root(request):
    return JSONResponse({
        "name": "건축HUB MCP",
        "version": __version__,
        "transport": "streamable-http",
        "endpoint": "/mcp",
        "tools": ["find_region", "building_profile", "building_floors", "price_history",
                  "building_ledger", "building_permit", "housing_permit",
                  "old_buildings", "district_stats", "demolitions", "permits_pipeline"],
        "source": "국토교통부 건축HUB (data.go.kr)",
    })


def main():
    parser = argparse.ArgumentParser(description="건축HUB MCP 서버")
    parser.add_argument("--transport", choices=["stdio", "http"],
                        default=os.environ.get("MCP_TRANSPORT", "stdio"))
    parser.add_argument("--host", default=os.environ.get("HOST", "0.0.0.0"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", "8000")))
    args = parser.parse_args()

    if args.transport == "http":
        mcp.run(transport="http", host=args.host, port=args.port)
    else:
        mcp.run()


if __name__ == "__main__":
    main()
