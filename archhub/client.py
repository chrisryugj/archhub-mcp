"""건축HUB API 클라이언트.

PublicDataReader의 get_data()는 동 전체를 numOfRows=99999로 한 번에 받고
requests에 timeout이 없어 MCP(빠른 응답)에 부적합하다. 따라서 HTTP 호출은
직접 제어(timeout/numOfRows/pageNo)하되, 라이브러리의 자산 두 가지만 재활용한다:
  - meta_dict[type]["url"]  : 조회 유형 → 엔드포인트 URL 매핑
  - translate_columns(df)   : 영문 → 한글 컬럼 rename
"""

import time
from typing import Optional

import pandas as pd
import requests
from PublicDataReader import (
    BuildingLedger,
    BuildingLicense,
    HousingLicense,
    code_bdong,
)

from .errors import ArchHubError, NO_KEY, INVALID_PARAM, API_ERROR, NOT_FOUND

requests.packages.urllib3.disable_warnings()  # data.go.kr는 http + 자가서명 경고 발생

# 조회 유형(소유자 제외 — 개인정보·별도 엔드포인트라 MVP 범위 밖)
LEDGER_TYPES = [
    "기본개요", "총괄표제부", "표제부", "층별개요", "부속지번",
    "전유공용면적", "오수정화시설", "주택가격", "전유부", "지역지구구역",
]
PERMIT_TYPES = [
    "기본개요", "동별개요", "층별개요", "호별개요", "대수선", "공작물관리대장",
    "철거멸실관리대장", "가설건축물", "오수정화시설", "주차장", "부설주차장",
    "전유공용면적", "호별전유공용면적", "지역지구구역", "도로명대장", "대지위치", "주택유형",
]
HOUSING_TYPES = [
    "기본개요", "동별개요", "층별개요", "호별개요", "부대시설", "오수정화시설",
    "주차장", "부설주차장", "전유공용면적", "행위호전유공용면적", "행위개요",
    "관리공동형별개요", "관리공동부대복리시설", "지역지구구역", "복리분양시설", "대지위치",
]

KINDS = {
    "ledger": ("건축물대장", LEDGER_TYPES),
    "permit": ("건축인허가", PERMIT_TYPES),
    "housing": ("주택인허가", HOUSING_TYPES),
}

# 건축HUB는 numOfRows가 100을 넘으면 100으로 캡한다(서버 상한, 실측). 100 이하는 존중.
# 따라서 한 페이지 최대는 100건이며, 더 필요하면 pageNo를 증가시킨다.
MAX_NUM_ROWS = 100

# 건축HUB는 numOfRows 요청과 무관하게 페이지당 최대 100건만 반환한다(서버 정책, 실측).
# fetch_all 분석은 이 행 상한까지만 수집(응답시간 폭주 방지). 자양동(6057건)은 완수,
# 1만건 초과 동만 일부 수집되며 호출측이 len(df) < total 로 절단을 감지한다.
MAX_FETCH_ROWS = 10000


class ArchHubClient:
    def __init__(self, service_key: str, timeout: int = 30):
        self.service_key = (service_key or "").strip()
        self.timeout = timeout
        # 메타/컬럼매핑 재활용 목적. 키 없어도 인스턴스화 가능해야 함.
        self._inst = {
            "ledger": BuildingLedger(self.service_key or "x"),
            "permit": BuildingLicense(self.service_key or "x"),
            "housing": HousingLicense(self.service_key or "x"),
        }
        self._bdong: Optional[pd.DataFrame] = None

    # ---- 지역코드 ----

    def bdong_table(self) -> pd.DataFrame:
        """법정동코드 테이블(현행만) 1회 로드 후 캐시."""
        if self._bdong is None:
            df = code_bdong()
            df = df[df["말소일자"].astype(str).str.strip() == ""].copy()
            self._bdong = df
        return self._bdong

    def find_region(self, keyword: str) -> pd.DataFrame:
        """주소 키워드(공백 구분, AND)로 법정동을 검색. sigungu_code/bdong_code 컬럼 부여."""
        df = self.bdong_table()
        hay = (
            df["시군구명"].astype(str) + " "
            + df["읍면동명"].astype(str) + " "
            + df["동리명"].astype(str)
        )
        mask = pd.Series([True] * len(df), index=df.index)
        for term in keyword.split():
            mask &= hay.str.contains(term, na=False)
        res = df[mask].copy()
        code = res["법정동코드"].astype(str)
        res["sigungu_code"] = code.str[:5]
        res["bdong_code"] = code.str[5:]
        return res

    # ---- 데이터 조회 ----

    def query(
        self,
        kind: str,
        type_name: str,
        sigungu_code: str,
        bdong_code: str,
        bun: Optional[str] = None,
        ji: Optional[str] = None,
        num_rows: int = 100,
        page_no: int = 1,
        translate: bool = True,
        fetch_all: bool = False,
    ) -> tuple[pd.DataFrame, int]:
        """건축HUB 데이터를 직접 REST로 조회. (DataFrame, totalCount) 반환.

        fetch_all=True면 페이지를 순회해 전체 수집(분석 도구 전용, 느릴 수 있음).
        """
        if not self.service_key:
            raise ArchHubError(
                "서비스 키가 없습니다. 환경변수 ARCHHUB_SERVICE_KEY를 설정하세요.",
                code=NO_KEY,
            )
        if kind not in KINDS:
            raise ArchHubError(f"알 수 없는 종류: {kind} (ledger/permit/housing)", code=INVALID_PARAM)
        _, valid_types = KINDS[kind]
        if type_name not in valid_types:
            raise ArchHubError(
                f"잘못된 조회 유형 '{type_name}'. 가능값: {', '.join(valid_types)}",
                code=INVALID_PARAM,
            )

        inst = self._inst[kind]
        url = inst.meta_dict[type_name]["url"]
        rows = min(max(int(num_rows), 1), MAX_NUM_ROWS)

        base_params = {
            "serviceKey": self.service_key,
            "sigunguCd": sigungu_code,
            "bjdongCd": bdong_code,
            "numOfRows": MAX_NUM_ROWS if fetch_all else rows,
            "_type": "json",
        }
        if bun:
            base_params["bun"] = str(bun).strip().zfill(4)
        if ji:
            base_params["ji"] = str(ji).strip().zfill(4)

        frames: list[pd.DataFrame] = []
        page = 1 if fetch_all else page_no
        total = 0
        while True:
            params = dict(base_params, pageNo=page)
            sub, total = self._request_page(url, params)
            if len(sub):
                frames.append(sub)
            if not fetch_all:
                break
            # fetch_all: 다음 페이지 필요 여부 판단
            got = sum(len(f) for f in frames)
            if got >= total or len(sub) == 0:
                break
            if got >= MAX_FETCH_ROWS:
                break  # 행 상한 도달 — 일부만 수집(호출측이 len(df)<total로 감지)
            page += 1
            time.sleep(0.1)  # 과도한 연속요청 방지(페이지당 100건이라 호출 잦음)

        if frames:
            df = pd.concat(frames, axis=0, ignore_index=True)
        else:
            df = pd.DataFrame()

        if translate and len(df):
            df = inst.translate_columns(df)
        return df, total

    def _request_page(self, url: str, params: dict) -> tuple[pd.DataFrame, int]:
        """단일 페이지 요청 → (DataFrame, totalCount)."""
        try:
            r = requests.get(url, params=params, verify=False, timeout=self.timeout)
        except requests.Timeout:
            raise ArchHubError(
                f"API 응답 시간 초과({self.timeout}s). 동 전체보다 번지(bun)를 지정하면 빨라집니다.",
                code=API_ERROR,
            )
        except requests.RequestException as e:
            raise ArchHubError(f"API 요청 실패: {e}", code=API_ERROR)

        try:
            j = r.json()
        except ValueError:
            raise ArchHubError(f"응답 파싱 실패(HTTP {r.status_code}). 키 등록/서비스 상태를 확인하세요.", code=API_ERROR)

        resp = j.get("response")
        if not resp:
            raise ArchHubError(f"비정상 응답: {str(j)[:200]}", code=API_ERROR)
        header = resp.get("header", {})
        if header.get("resultCode") not in ("00", "0"):
            raise ArchHubError(
                f"API 오류: {header.get('resultMsg', '알 수 없음')} (code={header.get('resultCode')})",
                code=API_ERROR,
            )

        body = resp.get("body", {})
        total = int(body.get("totalCount") or 0)
        items = body.get("items")
        if not items:
            return pd.DataFrame(), total
        item = items.get("item") if isinstance(items, dict) else items
        if item is None:
            return pd.DataFrame(), total
        if isinstance(item, dict):
            item = [item]
        return pd.DataFrame(item), total
