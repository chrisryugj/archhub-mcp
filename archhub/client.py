"""건축HUB API 클라이언트.

PublicDataReader의 get_data()는 동 전체를 numOfRows=99999로 한 번에 받고
requests에 timeout이 없어 MCP(빠른 응답)에 부적합하다. 따라서 HTTP 호출은
직접 제어(timeout/numOfRows/pageNo)하되, 라이브러리의 자산 두 가지만 재활용한다:
  - meta_dict[type]["url"]  : 조회 유형 → 엔드포인트 URL 매핑
  - translate_columns(df)   : 영문 → 한글 컬럼 rename
"""

import datetime
import json
import logging
import os
import threading
import time
from collections import OrderedDict
from pathlib import Path
from typing import Optional

import pandas as pd
import requests
from PublicDataReader import (
    BuildingLedger,
    BuildingLicense,
    HousingLicense,
)

from .errors import ArchHubError, NO_KEY, INVALID_PARAM, API_ERROR

# stderr 전용 로거 — stdout은 stdio MCP의 JSON-RPC 스트림이라 절대 오염 금지.
# 핸들러 설정(basicConfig)은 server.main()에서 1회 수행한다.
logger = logging.getLogger("archhub")

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
MAX_FETCH_PAGES = 100               # 100건/page → 행 상한과 정합(폭주 페이지 루프 차단)
FETCH_ALL_DEADLINE_S = 60           # 동 전체 수집 총 시간 상한(초) — 워커 장시간 점유 방지

# 응답 캐시(TTL+LRU): 건축물대장은 갱신 주기가 길어(일 단위) 6시간 캐시가 안전하다.
# 같은 페이지 재요청 시 외부 API 호출·일일 캡 소모를 모두 절약한다.
CACHE_TTL_S = 6 * 3600
CACHE_MAX_ENTRIES = 512

# 공용키 일일 호출 캡. 공공데이터포털 일 한도 보호용. 0(기본)이면 미적용.
# 운영(공개 remote)에서는 키 한도에 맞춰 ARCHHUB_DAILY_CALL_CAP을 설정 권장.
# 주의: 카운터는 프로세스 로컬이라 머신을 2대 이상으로 스케일하면 실효 한도 = 머신수×CAP
# (분산 보장 아님). 단일 머신 전제에서만 정확하다.
DAILY_CALL_CAP = int(os.environ.get("ARCHHUB_DAILY_CALL_CAP", "0") or "0")

# 법정동코드 JSON(현행 전체) — WooilJeong/code 저장소. PublicDataReader.code_bdong()은
# timeout 없이 받고 stdout에 print()를 한다(stdio MCP의 JSON-RPC를 오염시킴). 그래서
# 같은 URL을 timeout 걸어 직접 받고 디스크에 캐시한다(stdout 무오염).
BDONG_JSON_URL = "https://raw.githubusercontent.com/WooilJeong/code/main/code/code_dong/code_bdong.json"
BDONG_CACHE_PATH = Path(
    os.environ.get("ARCHHUB_CACHE_DIR") or (Path.home() / ".cache" / "archhub-mcp")
) / "code_bdong.json"
BDONG_FETCH_TIMEOUT = 30


class _TTLCache:
    """in-memory TTL+LRU 캐시 (표준 라이브러리만 — OrderedDict 기반, 신규 의존성 금지).

    maxsize 초과 시 가장 오래 안 쓴 항목부터 제거(LRU). TTL 경과 항목은 get 시 폐기.
    FastMCP가 동기 도구를 워커 스레드풀에서 돌리므로 get/set은 Lock으로 직렬화한다
    (OrderedDict의 move_to_end/popitem 동시 호출은 내부 상태를 깨뜨릴 수 있음).
    """

    def __init__(self, maxsize: int = CACHE_MAX_ENTRIES, ttl: float = CACHE_TTL_S):
        self.maxsize = maxsize
        self.ttl = ttl
        self._d: OrderedDict = OrderedDict()
        self._lock = threading.Lock()

    def get(self, key):
        with self._lock:
            item = self._d.get(key)
            if item is None:
                return None
            ts, val = item
            if time.monotonic() - ts > self.ttl:
                del self._d[key]  # 만료 — 폐기
                return None
            self._d.move_to_end(key)  # LRU 갱신
            return val

    def set(self, key, val) -> None:
        with self._lock:
            self._d[key] = (time.monotonic(), val)
            self._d.move_to_end(key)
            while len(self._d) > self.maxsize:
                self._d.popitem(last=False)


def _validate_codes(sigungu_code, bdong_code) -> None:
    """sigungu_code/bdong_code가 5자리 숫자인지 검증(외부 API 호출 전 차단)."""
    for name, v in (("sigungu_code", sigungu_code), ("bdong_code", bdong_code)):
        s = str(v).strip()
        # isascii 동시 검사: 전각 숫자('１１２１５')는 isdigit=True지만 API에선 무효
        if not (s.isascii() and s.isdigit() and len(s) == 5):
            raise ArchHubError(
                f"{name}는 5자리 숫자여야 합니다(받음: '{v}'). find_region으로 코드를 확인하세요.",
                code=INVALID_PARAM,
            )


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
        # 페이지 반복 호출(fetch_all 최대 100p)에 keep-alive 재사용 — 페이지당 TLS 핸드셰이크 제거.
        self._session = requests.Session()
        # 응답 페이지 TTL 캐시 — 동일 조회 반복 시 외부 호출·일일 캡 절약.
        self._cache = _TTLCache()
        # data.go.kr 외부 호출 건수(프로세스 생존 동안). 공용키 일 한도 관측용.
        # 페이지당 1콜이라 fetch_all은 여러 번 증가. 정확한 잔여량은 API가 안 줘서 근사.
        self.api_calls = 0
        # 일일 캡(DAILY_CALL_CAP)용 — 날짜가 바뀌면 0으로 리셋.
        self._calls_today = 0
        self._calls_date = datetime.date.today().isoformat()
        # 카운터 갱신 직렬화 — FastMCP 워커 스레드 동시 호출 대비.
        self._count_lock = threading.Lock()

    # ---- 지역코드 ----

    def bdong_table(self) -> pd.DataFrame:
        """법정동코드 테이블(현행만) 1회 로드 후 캐시."""
        if self._bdong is None:
            raw = self._load_bdong_json()
            df = pd.DataFrame(raw["data"]).fillna("")
            df = df[df["말소일자"].astype(str).str.strip() == ""].copy()
            self._bdong = df
        return self._bdong

    def _load_bdong_json(self) -> dict:
        """법정동 JSON을 디스크 캐시에서 읽고, 없으면 timeout 걸어 받아 캐시한다.

        PublicDataReader.code_bdong()을 쓰지 않는 이유: timeout이 없어 워커가
        무한 대기할 수 있고, 성공 시 stdout에 print()를 해 stdio MCP의 JSON-RPC
        스트림을 오염시킨다. 여기서는 stdout을 건드리지 않고 timeout을 강제한다.
        """
        if BDONG_CACHE_PATH.exists():
            try:
                return json.loads(BDONG_CACHE_PATH.read_text(encoding="utf-8"))
            except (ValueError, OSError):
                pass  # 캐시 손상 → 재다운로드
        try:
            r = requests.get(BDONG_JSON_URL, timeout=BDONG_FETCH_TIMEOUT)
            r.raise_for_status()
            data = r.json()
        except requests.RequestException as e:
            raise ArchHubError(
                f"법정동코드 데이터를 받지 못했습니다: {e}. 네트워크를 확인하세요.",
                code=API_ERROR,
            )
        try:
            BDONG_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
            BDONG_CACHE_PATH.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        except OSError:
            pass  # 캐시 못 써도 메모리로는 동작
        return data

    def find_region(self, keyword: str) -> pd.DataFrame:
        """주소 키워드(공백 구분, AND)로 법정동을 검색. sigungu_code/bdong_code 컬럼 부여."""
        df = self.bdong_table()
        hay = (
            df["시도명"].astype(str) + " "
            + df["시군구명"].astype(str) + " "
            + df["읍면동명"].astype(str) + " "
            + df["동리명"].astype(str)
        )
        mask = pd.Series([True] * len(df), index=df.index)
        for term in keyword.split():
            # regex=False: 사용자 검색어가 정규식으로 해석되면 괄호 등에서 re.error 크래시
            mask &= hay.str.contains(term, na=False, regex=False)
        res = df[mask]
        code = res["법정동코드"].astype(str)
        # assign: 새 DataFrame 반환 — pandas 3.0 Copy-on-Write에서 chained assignment 무동작 회피
        return res.assign(sigungu_code=code.str[:5], bdong_code=code.str[5:])

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
        _validate_codes(sigungu_code, bdong_code)
        for label, v in (("bun", bun), ("ji", ji)):
            if v not in (None, "") and not str(v).strip().isdigit():
                raise ArchHubError(f"{label}은 숫자여야 합니다(받음: '{v}').", code=INVALID_PARAM)

        inst = self._inst[kind]
        # 건축HUB 엔드포인트는 https를 제공한다. 평문 http면 키·응답이 노출되므로 강제 승격.
        url = inst.meta_dict[type_name]["url"].replace("http://", "https://", 1)
        rows = min(max(int(num_rows), 1), MAX_NUM_ROWS)
        page_no = max(int(page_no), 1)
        if page_no > MAX_FETCH_PAGES:
            # 조용한 클램프 금지 — 사용자가 100페이지 결과를 101페이지 결과로 오인하게 된다
            raise ArchHubError(
                f"page는 1~{MAX_FETCH_PAGES} 범위여야 합니다(받음: {page_no}). "
                f"페이지당 최대 {MAX_NUM_ROWS}건이므로 그 이상은 bun(번지)으로 좁혀 조회하세요.",
                code=INVALID_PARAM,
            )

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
        deadline = time.monotonic() + FETCH_ALL_DEADLINE_S
        while True:
            params = dict(base_params, pageNo=page)
            sub, total = self._request_page(url, params)
            if len(sub):
                frames.append(sub)
            if not fetch_all:
                break
            # fetch_all: 다음 페이지 필요 여부 판단(아래 상한 중 하나라도 닿으면 절단)
            got = sum(len(f) for f in frames)
            if got >= total or len(sub) == 0:
                break
            if got >= MAX_FETCH_ROWS or page >= MAX_FETCH_PAGES:
                # 행/페이지 상한 도달 — 일부만 수집(호출측이 len(df)<total로 감지)
                logger.warning("fetch_all 절단(행/페이지 상한): %d/%d건 수집 (url=%s)", got, total, url)
                break
            if time.monotonic() >= deadline:
                # 총 데드라인 초과 — 워커 장시간 점유 방지
                logger.warning("fetch_all 절단(데드라인 %ds): %d/%d건 수집 (url=%s)", FETCH_ALL_DEADLINE_S, got, total, url)
                break
            page += 1
            time.sleep(0.1)  # 과도한 연속요청 방지(페이지당 100건이라 호출 잦음)

        if frames:
            df = pd.concat(frames, axis=0, ignore_index=True)
        else:
            df = pd.DataFrame()

        if translate and len(df):
            # 라이브러리 컬럼 매핑 재활용. 주의: PublicDataReader 1.1.1.post2는 기본개요의
            # 건축구분코드명↔건축구분코드를 뒤바꿔 매핑한다(실측). 호출측(formatting._permit_kind)이
            # 값이 숫자(코드값)인지로 swap을 자가 감지해 보정하므로, 라이브러리가 swap을
            # 고쳐도 깨지지 않는다(버전 상한 불필요).
            df = inst.translate_columns(df)
        return df, total

    def _enforce_daily_cap(self) -> None:
        """일일 호출 캡 적용. 날짜가 바뀌면 카운터를 리셋한다. (Lock으로 직렬화)"""
        with self._count_lock:
            today = datetime.date.today().isoformat()
            if today != self._calls_date:
                self._calls_date = today
                self._calls_today = 0
            self._calls_today += 1
            exceeded = DAILY_CALL_CAP and self._calls_today > DAILY_CALL_CAP
        if exceeded:
            logger.warning("일일 호출 캡 도달: %d건 (오늘 %d번째 요청 차단)", DAILY_CALL_CAP, self._calls_today)
            raise ArchHubError(
                f"오늘 공용키 호출 한도({DAILY_CALL_CAP}건)를 초과했습니다. 잠시 후/내일 다시 시도하세요.",
                code=API_ERROR,
            )

    def _request_page(self, url: str, params: dict) -> tuple[pd.DataFrame, int]:
        """단일 페이지 요청 → (DataFrame, totalCount). 결과는 TTL 캐시(6시간)한다.

        캐시 키 = url(조회 종류·유형 식별) + serviceKey 제외 파라미터(지역코드·번지·페이지 등).
        캐시 히트는 외부 호출이 아니므로 일일 캡·api_calls에 미산입.
        빈 결과는 캐시하지 않는다(일시 장애가 6시간 고착되는 것 방지).
        """
        cache_key = (url, tuple(sorted((k, str(v)) for k, v in params.items() if k != "serviceKey")))
        cached = self._cache.get(cache_key)
        if cached is not None:
            df, total = cached
            return df.copy(), total  # 호출측 변형이 캐시를 오염시키지 않도록 사본 반환

        self._enforce_daily_cap()
        self.api_calls += 1
        try:
            r = self._session.get(url, params=params, timeout=self.timeout)
        except requests.Timeout:
            logger.warning("외부 API 시간 초과(%ds): %s", self.timeout, url)
            raise ArchHubError(
                f"API 응답 시간 초과({self.timeout}s). 동 전체보다 번지(bun)를 지정하면 빨라집니다.",
                code=API_ERROR,
            )
        except requests.RequestException as e:
            logger.warning("외부 API 요청 실패: %s (url=%s)", e, url)
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
        item = (items.get("item") if isinstance(items, dict) else items) if items else None
        if item is None:
            return pd.DataFrame(), total  # 빈 결과는 캐시하지 않음
        if isinstance(item, dict):
            item = [item]
        df = pd.DataFrame(item)
        if len(df):
            self._cache.set(cache_key, (df, total))
        return df, total
