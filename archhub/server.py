"""건축HUB MCP 서버.

stdio 모드(로컬 Claude Desktop/Code)와 streamable-http 모드(fly.io remote 커넥터)를
모두 지원한다. 공용 서비스키는 환경변수 ARCHHUB_SERVICE_KEY로 주입한다.
"""

import argparse
import datetime
import os

import pandas as pd
from fastmcp import FastMCP
from starlette.responses import JSONResponse

from . import __version__
from .client import ArchHubClient, KINDS, LEDGER_TYPES, PERMIT_TYPES, HOUSING_TYPES
from .errors import not_found, format_error
from .formatting import df_to_text, profile_to_text

SERVICE_KEY = os.environ.get("ARCHHUB_SERVICE_KEY", "").strip()
client = ArchHubClient(SERVICE_KEY)

mcp = FastMCP(
    name="archhub",
    instructions=(
        "국토교통부 건축HUB(공공데이터포털) 건축물대장·건축인허가·주택인허가 조회 서버. "
        "주소는 먼저 find_region으로 sigungu_code/bdong_code를 얻은 뒤 다른 도구에 넘긴다. "
        "데이터는 모두 공식 API 실측값이며, 결과가 없으면 추측하지 말고 '데이터 없음'을 보고한다."
    ),
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
    """한 필지(번지)의 건축물 핵심 스펙을 종합 카드로 한 번에 조회한다.

    표제부를 1회 호출해 동(棟)별로 주용도·구조·규모(층수/높이/연면적/대지면적)·
    건폐율·용적률(미기재 시 면적으로 계산)·세대/호수·주차·사용승인일·내진·에너지효율을
    카드 형식으로 묶어준다. type_name을 바꿔 여러 번 호출할 필요 없이, 건물 한 채의
    전반을 파악할 때 가장 먼저 쓰는 도구다. (중개·감정평가·건축 실무용)

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
    return profile_to_text(df, total, max_buildings)


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

    this_year = datetime.date.today().year
    d = df.copy()
    d[col] = d[col].astype(str).str.strip()
    d = d[d[col].str.len() >= 4]
    d["승인연도"] = pd.to_numeric(d[col].str[:4], errors="coerce")
    d = d.dropna(subset=["승인연도"])
    d["경과연수"] = this_year - d["승인연도"].astype(int)
    old = d[d["경과연수"] >= min_age_years].sort_values("경과연수", ascending=False)
    if len(old) == 0:
        return not_found(f"경과 {min_age_years}년 이상 건축물 없음 (표제부 전체 {total}건)")

    candidate = ["건물명", "도로명대지위치", "대지위치", "주용도코드명",
                 "사용승인일", "경과연수", "연면적", "지상층수", "세대수"]
    cols = [c for c in candidate if c in old.columns]
    note = f"표제부 {total}건{trunc} 중 경과 {min_age_years}년↑ {len(old)}건 (경과연수 내림차순)"
    return df_to_text(old[cols], max_rows=top, note=note)


# ---- HTTP 라우트 ----


@mcp.custom_route("/health", methods=["GET"])
async def health(request):
    return JSONResponse({"status": "ok", "version": __version__, "key_loaded": bool(SERVICE_KEY)})


@mcp.custom_route("/", methods=["GET"])
async def root(request):
    return JSONResponse({
        "name": "건축HUB MCP",
        "version": __version__,
        "transport": "streamable-http",
        "endpoint": "/mcp",
        "tools": ["find_region", "building_profile", "building_ledger",
                  "building_permit", "housing_permit", "old_buildings"],
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
