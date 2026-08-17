"""건축HUB MCP 서버.

stdio 모드(로컬 Claude Desktop/Code)와 streamable-http 모드(fly.io remote 커넥터)를
모두 지원한다. 공용 서비스키는 환경변수 ARCHHUB_SERVICE_KEY로 주입한다.
"""

import argparse
import datetime
import logging
import os
import re
import sys
from pathlib import Path

import pandas as pd
from fastmcp import FastMCP
from starlette.middleware import Middleware
from starlette.responses import JSONResponse

from . import __version__
from .client import ArchHubClient, KINDS, DAILY_CALL_CAP
from .errors import not_found, format_error
from .formatting import (
    df_to_text, profile_to_text, district_to_text, floors_to_text,
    price_history_to_text, demolitions_to_text, pipeline_to_text, seismic_to_text,
    parcel_history_to_text, temp_buildings_to_text,
    _date, _age_years, _num,
)


def _load_env_local() -> None:
    """.env.local(KEY=VALUE)을 os.environ에 주입한다(이미 설정된 키는 보존).

    README가 안내하는 .env.local을 실제로 로드한다. python-dotenv 의존 없이 stdlib로
    처리(로컬 편의 한정 — 운영은 fly secrets/환경변수 사용).

    cwd와 패키지 부모를 모두 순회한다(빈 .env.local에 막히지 않도록). cwd를 먼저 읽고
    'k not in os.environ' 가드로 먼저 채운 키를 보존하므로 cwd가 우선한다.

    import 시점이 아니라 main()에서 호출한다 — 테스트가 import만 해도 os.environ이
    변조되는 부작용 방지."""
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


SERVICE_KEY = os.environ.get("ARCHHUB_SERVICE_KEY", "").strip()
KEY_EXPIRES = os.environ.get("ARCHHUB_KEY_EXPIRES", "").strip()  # 공용키 만료일 YYYY-MM-DD(선택)
MCP_TOKEN = os.environ.get("ARCHHUB_MCP_TOKEN", "").strip()      # 설정 시 remote 접근에 Bearer 토큰 요구
client = ArchHubClient(SERVICE_KEY)


def _apply_env() -> None:
    """환경변수를 모듈 상태에 재반영. main()에서 .env.local 로드 후 호출한다.

    import 시점엔 프로세스 환경변수만 읽으므로(.env.local 미로드), .env.local로
    키를 공급하는 로컬 stdio 실행은 이 함수가 모듈 상태를 갱신해야 동작한다."""
    global SERVICE_KEY, KEY_EXPIRES, MCP_TOKEN
    SERVICE_KEY = os.environ.get("ARCHHUB_SERVICE_KEY", "").strip()
    KEY_EXPIRES = os.environ.get("ARCHHUB_KEY_EXPIRES", "").strip()
    MCP_TOKEN = os.environ.get("ARCHHUB_MCP_TOKEN", "").strip()
    client.service_key = SERVICE_KEY
    if MCP_TOKEN and mcp.auth is None:
        mcp.auth = _build_auth()


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


def _fetch_septic(sigungu_code: str, bdong_code: str, bun: str, ji: str):
    """필지의 오수정화시설(정화조) 형식·용량 요약. 실패/없으면 None (profile 부가정보라 조용히 생략).

    정화조 용량(인용)은 용도변경·증축 검토 시 오수발생량 산정의 출발점이라 실무 수요가 크다."""
    try:
        df, _ = client.query("ledger", "오수정화시설", sigungu_code, bdong_code,
                             bun=bun, ji=ji, num_rows=20)
    except Exception:
        return None
    if len(df) == 0:
        return None
    items = []
    for _, row in df.head(3).iterrows():
        form = str(row.get("형식코드명", "")).strip()
        seg = [form] if form and form.lower() != "nan" else []
        cap_person = _num(row.get("용량(인용)"))
        cap_m3 = _num(row.get("용량(루베)"))
        if cap_person:
            seg.append(f"{cap_person:g}인용")
        elif cap_m3:
            seg.append(f"{cap_m3:g}㎥")
        if seg:
            items.append(" ".join(seg))
    return " · ".join(dict.fromkeys(items)) or None

mcp = FastMCP(
    name="archhub",
    instructions=(
        "국토교통부 건축HUB(공공데이터포털) 건축물대장·건축인허가·주택인허가 조회 서버. "
        "주소는 먼저 find_region으로 sigungu_code/bdong_code를 얻은 뒤 다른 도구에 넘긴다"
        "(번지가 섞인 주소는 find_region이 bun/ji도 분리해 안내한다). "
        "필지 하나의 현황은 building_profile, 과거 이력은 parcel_history부터 시작하면 빠르다. "
        "데이터는 모두 공식 API 실측값이며, 결과가 없으면 추측하지 말고 '데이터 없음'을 보고한다."
    ),
    auth=_build_auth(),
    # version 을 넘기지 않으면 FastMCP 가 자기 라이브러리 버전으로 serverInfo 를 채운다
    # — 클라이언트에 3.4.x 가 이 서버 버전으로 표시된다.
    version=__version__,
)


# ---- 도구 ----

# 번지 토큰: '680', '680-63', '680번지', '680-63번지'. 동 이름과 구분해 분리 파싱한다.
_BUNJI_RE = re.compile(r"^(\d{1,4})(?:-(\d{1,4}))?(?:번지)?$")


@mcp.tool
def find_region(keyword: str, limit: int = 20) -> str:
    """주소 키워드로 시군구코드/법정동코드를 조회한다.

    예: "광진구 자양동" → 해당 동의 sigungu_code(5자리)·bdong_code(5자리).
    여기서 얻은 코드를 building_profile / parcel_history / building_data /
    old_buildings 등 다른 도구의 sigungu_code·bdong_code 인자로 사용한다.
    "자양동 680-63"처럼 번지가 섞여 있으면 자동으로 분리해 bun/ji 값을 함께 안내한다.

    Args:
        keyword: 공백으로 구분된 주소 키워드(시/군/구/동, 번지 포함 가능). 모두 포함하는 행을 검색.
        limit: 최대 반환 행 수.
    """
    bun = ji = None
    region_terms = []
    for term in keyword.split():
        m = _BUNJI_RE.fullmatch(term)
        if m and bun is None:
            bun, ji = m.group(1), m.group(2)
        else:
            region_terms.append(term)
    if not region_terms:
        return not_found(
            f"'{keyword}' 에 지역 키워드가 없습니다(번지만 입력됨).",
            ["동 이름과 함께 검색 (예: '자양동 680-63')"],
        )
    try:
        res = client.find_region(" ".join(region_terms))
    except Exception as e:
        return format_error(e, "find_region")
    if len(res) == 0:
        return not_found(f"'{keyword}' 에 해당하는 지역 없음", [
            "시/구/동 이름 일부로 다시 검색",
            "행정동(자양1동 등)은 법정동이 아님 — 숫자 뗀 동 이름(자양동)으로 재검색",
        ])
    cols = ["시도명", "시군구명", "읍면동명", "동리명", "법정동코드", "sigungu_code", "bdong_code"]
    out = res[cols].copy()
    # 읍면동명·동리명 모두 공백 = 시군구 단위 행 — bdong_code(00000)로는 동 단위 조회 불가
    gu_level = (
        (out["읍면동명"].astype(str).str.strip() == "")
        & (out["동리명"].astype(str).str.strip() == "")
    )
    if gu_level.any():
        # 단일 스텝 할당 — chained assignment는 pandas 3.0(Copy-on-Write)에서 무동작
        out["비고"] = gu_level.map({True: "구 단위 — bdong_code로 사용 불가", False: ""})
    note = "아래 sigungu_code/bdong_code를 다른 도구의 인자로 사용하세요."
    if bun:
        note += f" 입력의 번지는 bun={bun}" + (f", ji={ji}" if ji else "") + " 로 전달하세요."
    return df_to_text(out, max_rows=limit, note=note)


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
def building_data(
    kind: str,
    type_name: str,
    sigungu_code: str,
    bdong_code: str,
    bun: str = "",
    ji: str = "",
    max_rows: int = 50,
    page: int = 1,
) -> str:
    """건축HUB 원천 데이터를 직접 조회한다 (건축물대장·건축인허가·주택인허가 통합, 고급용).

    종합카드(building_profile)·연혁(parcel_history)·통계(district_stats) 등 가공 도구로
    답이 안 되는 원본 행이 필요할 때만 쓴다. kind로 대장 종류를, type_name으로 세부
    유형을 고른다.

    Args:
        kind: 대장 종류 — ledger(건축물대장) | permit(건축인허가) | housing(주택인허가).
        type_name: 조회 유형. kind별 가능값 —
            ledger: 기본개요|총괄표제부|표제부|층별개요|부속지번|전유공용면적|오수정화시설|
                주택가격|전유부|지역지구구역
            permit: 기본개요|동별개요|층별개요|호별개요|대수선|공작물관리대장|철거멸실관리대장|
                가설건축물|오수정화시설|주차장|부설주차장|전유공용면적|호별전유공용면적|
                지역지구구역|도로명대장|대지위치|주택유형
            housing: 기본개요|동별개요|층별개요|호별개요|부대시설|오수정화시설|주차장|부설주차장|
                전유공용면적|행위호전유공용면적|행위개요|관리공동형별개요|관리공동부대복리시설|
                지역지구구역|복리분양시설|대지위치
        sigungu_code: 시군구 5자리 코드 (find_region으로 조회).
        bdong_code: 읍면동 5자리 코드.
        bun: 번지 본번(생략 시 동 전체). 큰 동은 번지 지정이 빠름.
        ji: 번지 부번.
        max_rows: 한 페이지 반환 행 수(최대 100; 더 필요하면 page를 증가).
        page: 페이지 번호(동 전체가 max_rows보다 많을 때 증가).
    """
    if kind not in KINDS:
        return not_found(
            f"알 수 없는 kind '{kind}' — ledger(건축물대장)/permit(건축인허가)/housing(주택인허가) 중 선택",
        )
    label = KINDS[kind][0]
    return _query(kind, label, type_name, sigungu_code, bdong_code, bun, ji, max_rows, page)


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
            "building_profile은 번지(bun)가 필요합니다. 동 전체 조회는 building_data(kind=ledger)를 쓰세요.",
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
    septic = _fetch_septic(sigungu_code, bdong_code, bun, ji)
    return profile_to_text(df, total, max_buildings, zoning=zoning, septic=septic)


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
    unknown = int(d["경과연수"].isna().sum())  # 사용승인일 미상/파싱불가 → 노후 판정 불가로 제외됨
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
    unknown_note = f" · 승인일 미상 {unknown}건 제외" if unknown else ""
    note = f"표제부 {total}건{trunc} 중 경과 {min_age_years}년↑ {len(old)}건 (경과연수 내림차순){unknown_note}"
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
    공급 파이프라인을 파악한다. 허가 후 5년 경과 + 미착공 건은 건축법상 실효 가능성이
    높아 '장기 미착공'으로 분리 집계한다(진행중 과대집계 방지).
    (디벨로퍼·공무원용) 동 전체를 받아 다소 느릴 수 있다.

    Args:
        sigungu_code: 시군구 5자리 코드 (find_region으로 조회).
        bdong_code: 읍면동 5자리 코드.
        since_year: 이 연도 이후(건축허가일 기준)만. 0(기본)이면 최근 5년.
            전체 이력이 필요하면 1900 등 충분히 과거 연도를 지정.
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
    # 기본(0)은 최근 5년 — 수십 년 치 실효·미착공 허가가 '진행중'으로 과대집계되는 것 방지
    if not since_year:
        since_year = datetime.date.today().year - 5
    return pipeline_to_text(df, total, trunc, since_year, top)


@mcp.tool
def seismic_check(
    sigungu_code: str,
    bdong_code: str,
    min_floors: int = 3,
    max_buildings: int = 30,
) -> str:
    """법정동의 내진설계 미적용 추정 건축물을 스캔한다 (내진 의무화 연혁 기반).

    건축물대장 표제부 전체를 받아 사용승인일 시점의 내진설계 의무 기준
    (1988 도입: 6층↑/10만㎡↑ → 1995 확대 → 2005: 3층↑/1,000㎡↑ → 2015: 2층↑/500㎡↑ →
    2017.12: 2층↑(목구조 3층↑)/200㎡↑ + 모든 주택)에 승인연도×층수×연면적을 대입해,
    당시 의무 대상이 아니던 건물을 '내진설계 미적용 추정'으로 분류한다. 조적조·블록조 등
    취약 구조 + 고층 순으로 우선 점검 후보를 제시한다. (안전점검·정비사업·매입실사용)
    동 전체를 받으므로 응답이 다소 느릴 수 있다.

    Args:
        sigungu_code: 시군구 5자리 코드 (find_region으로 조회).
        bdong_code: 읍면동 5자리 코드.
        min_floors: 우선 점검 후보 목록에 올릴 최소 지상층수. 기본 3.
        max_buildings: 목록 최대 건수.
    """
    try:
        df, total = client.query("ledger", "표제부", sigungu_code, bdong_code, fetch_all=True)
    except Exception as e:
        return format_error(e, "seismic_check")
    if len(df) == 0:
        return not_found(
            f"표제부 데이터 없음 (sigungu={sigungu_code}, bdong={bdong_code})",
            ["find_region으로 코드 재확인"],
        )
    collected = len(df)
    trunc = f" (응답 한도로 {collected}건만 집계)" if collected < total else ""
    return seismic_to_text(df, total, trunc, min_floors, max_buildings)


@mcp.tool
def parcel_history(
    sigungu_code: str,
    bdong_code: str,
    bun: str,
    ji: str = "",
    top: int = 40,
) -> str:
    """한 필지의 건축 연혁 타임라인을 조회한다 (인허가 + 철거멸실 + 가설건축물 통합).

    건축인허가 기본개요·철거멸실관리대장·가설건축물을 한 번에 받아 허가→착공→사용승인,
    철거, 가설건축물 존치(만료 포함)를 오래된 순 타임라인으로 묶는다. "이 땅에 무슨 일이
    있었나"를 1콜로 — 민원 대응·이력 확인(공무원), 매입 실사(디벨로퍼·중개·감정평가)의
    출발점. 증축·대수선·용도변경 이력도 건축구분으로 드러난다.

    Args:
        sigungu_code: 시군구 5자리 코드 (find_region으로 조회).
        bdong_code: 읍면동 5자리 코드.
        bun: 번지 본번. **필수** (필지 단위 조회).
        ji: 번지 부번(생략 가능).
        top: 표시할 최대 이벤트 수.
    """
    if not str(bun).strip():
        return not_found(
            "parcel_history는 번지(bun)가 필요합니다.",
            ["find_region으로 코드 확인 후 bun(본번) 지정"],
        )
    frames = {}
    for label, type_name in (("permits", "기본개요"), ("demos", "철거멸실관리대장"),
                             ("temps", "가설건축물")):
        try:
            frames[label], _ = client.query(
                "permit", type_name, sigungu_code, bdong_code,
                bun=bun, ji=ji, num_rows=100,
            )
        except Exception as e:
            return format_error(e, f"parcel_history({type_name})")
    if all(len(f) == 0 for f in frames.values()):
        return not_found(
            f"필지 연혁 없음 (sigungu={sigungu_code}, bdong={bdong_code}, bun={bun}, ji={ji})",
            ["find_region으로 코드 재확인", "ji(부번) 조정"],
        )
    return parcel_history_to_text(frames["permits"], frames["demos"], frames["temps"],
                                  bun=bun, ji=ji, top=top)


@mcp.tool
def temp_buildings(
    sigungu_code: str,
    bdong_code: str,
    bun: str = "",
    ji: str = "",
    top: int = 30,
) -> str:
    """법정동(또는 필지)의 가설건축물 존치 현황을 만료 경과/임박 순으로 스캔한다.

    건축인허가 가설건축물 대장을 받아 허가대장 PK 단위로 묶고, 가설건축물존치만료일
    기준으로 ① 만료 경과 ② 만료임박(180일 이내) ③ 유효 ④ 미상을 집계한 뒤 만료 경과
    오래된 순 → 임박 순으로 우선 점검 후보를 제시한다. 존치기간 연장 신고 관리·정기
    점검(건축행정 공무원), 현장 가설사무소·견본주택 존치 확인(시공·디벨로퍼)용.
    동 전체를 받으므로 응답이 다소 느릴 수 있다(bun 지정 시 필지 한정).

    Args:
        sigungu_code: 시군구 5자리 코드 (find_region으로 조회).
        bdong_code: 읍면동 5자리 코드.
        bun: 번지 본번(생략 시 동 전체).
        ji: 번지 부번.
        top: 우선 점검 후보 최대 건수.
    """
    try:
        df, total = client.query("permit", "가설건축물", sigungu_code, bdong_code,
                                 bun=bun, ji=ji, fetch_all=True)
    except Exception as e:
        return format_error(e, "temp_buildings")
    if len(df) == 0:
        return not_found(
            f"가설건축물 데이터 없음 (sigungu={sigungu_code}, bdong={bdong_code})",
            ["find_region으로 코드 재확인"],
        )
    collected = len(df)
    trunc = f" (응답 한도로 {collected}건만 집계)" if collected < total else ""
    return temp_buildings_to_text(df, total, trunc, top)


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
                  "parcel_history", "temp_buildings", "building_data",
                  "old_buildings", "district_stats", "demolitions", "permits_pipeline",
                  "seismic_check"],
        "source": "국토교통부 건축HUB (data.go.kr)",
    })


class Utf8RequestBodyMiddleware:
    """POST 요청 본문을 UTF-8로 정규화하는 ASGI 미들웨어(http 트랜스포트 전용).

    한국어 Windows의 일부 MCP 클라이언트는 한글 인자(예: keyword="광진구 자양동")를
    CP949로 직렬화해 전송한다. 그러면 라우트의 json.loads(body)가 UnicodeDecodeError를
    던져 미처리 예외 → HTTP 500(-32603, "Error handling POST request")이 된다.
    라우트에 닿기 전에, 본문이 UTF-8이 아니면 CP949/EUC-KR로 관대 디코드해 UTF-8 bytes로
    바꿔 방어한다(이미 UTF-8이면 그대로 통과 — 정상 클라이언트엔 무영향).

    본문은 청크 경계에서 멀티바이트가 잘려 디코드가 깨지지 않도록 전부 모아 한 번에
    변환한다. MCP JSON-RPC 요청은 작아 버퍼링 비용이 무시할 수준이다.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope.get("method") != "POST":
            return await self.app(scope, receive, send)

        body = b""
        saw_request = False
        more = True
        while more:
            msg = await receive()
            if msg["type"] == "http.request":
                saw_request = True
                body += msg.get("body", b"")
                more = msg.get("more_body", False)
            else:
                more = False  # http.disconnect 등 — 정규화 없이 원본 흐름 위임
        if not saw_request:
            return await self.app(scope, receive, send)

        if body:
            try:
                body.decode("utf-8")
            except UnicodeDecodeError:
                for enc in ("cp949", "euc-kr"):
                    try:
                        body = body.decode(enc).encode("utf-8")
                        break
                    except UnicodeDecodeError:
                        continue  # 모두 실패하면 원본 유지(하위에서 판단)

        sent = False

        async def receive_normalized():
            nonlocal sent
            if not sent:
                sent = True
                return {"type": "http.request", "body": body, "more_body": False}
            return await receive()

        await self.app(scope, receive_normalized, send)


def main():
    # 로깅은 stderr로만 — stdout은 stdio MCP의 JSON-RPC 스트림이라 오염 금지.
    logging.basicConfig(stream=sys.stderr, level=logging.WARNING,
                        format="%(asctime)s %(name)s %(levelname)s %(message)s")
    _load_env_local()  # import 부작용 방지를 위해 여기서 로드(테스트는 main을 안 탄다)
    _apply_env()
    parser = argparse.ArgumentParser(description="건축HUB MCP 서버")
    parser.add_argument("--transport", choices=["stdio", "http"],
                        default=os.environ.get("MCP_TRANSPORT", "stdio"))
    parser.add_argument("--host", default=os.environ.get("HOST", "0.0.0.0"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", "8000")))
    args = parser.parse_args()

    if args.transport == "http":
        # 비-UTF-8(CP949 등) 요청 본문을 라우트 이전에 UTF-8로 정규화 — 한글 인자 500 방어.
        # stateless_http: 요청마다 새 transport. 끄면 FastMCP가 세션을 요구해
        # Mcp-Session-Id 없는 클라이언트에 "Bad Request: Missing session ID"(400)를 낸다.
        # 통합 호스트의 다른 MCP 4종(law/stats/patent/school)은 모두 stateless라 동작을 맞춘다.
        # 주의: stateless에서는 GET /mcp(SSE 스트림)가 막히고 POST/DELETE만 허용된다.
        mcp.run(transport="http", host=args.host, port=args.port,
                stateless_http=True,
                middleware=[Middleware(Utf8RequestBodyMiddleware)])
    else:
        mcp.run()


if __name__ == "__main__":
    main()
