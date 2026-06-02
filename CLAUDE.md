# archhub-mcp — 프로젝트 메모

국토교통부 건축HUB(공공데이터포털) → MCP 서버. Python + FastMCP 3.x.

## 구조

```
archhub/
  __init__.py     # __version__
  __main__.py     # python -m archhub 진입점
  server.py       # FastMCP 인스턴스 + 도구 11개 + /health,/ 라우트 + stdio/http main()
  client.py       # ArchHubClient — 직접 REST 호출 + 법정동코드 캐시 + api_calls 카운터
  errors.py       # [NOT_FOUND]/[ERROR] 포맷 (환각 방지), 키 마스킹
  formatting.py   # DataFrame → 텍스트(종합카드·동단위통계) + 출처 명시
```

## 핵심 설계 결정

- **호출은 직접 REST**: PublicDataReader의 `get_data()`는 `numOfRows=99999` 한 방 + timeout 없음 →
  MCP에 부적합. 그래서 `requests`로 timeout/numOfRows/pageNo 직접 제어.
- **라이브러리 재활용은 2가지만**: `meta_dict[type]["url"]`(엔드포인트 매핑), `translate_columns(df)`(한글 변환).
- **공용키 방식**: `ARCHHUB_SERVICE_KEY` 환경변수 하나로 모든 요청 처리 (BYOK 격리 없음).
- **remote 커넥터**: fly.io에 streamable-http로 떠서 URL만 등록하면 연결.

## 검증

```bash
# in-memory MCP Client로 도구 목록 + 실호출
ARCHHUB_SERVICE_KEY=... python -c "import asyncio; from fastmcp import Client; from archhub.server import mcp; ..."

# 단위테스트 (외부 API 비의존, mock)
pytest tests/
```

자양동 = sigungu `11215`, bdong `10500` (표제부 totalCount 6057).

## 실측한 API 동작 (추측 금지 — 코드에 의존)

- **페이지당 100건 고정**: `numOfRows>100`은 서버가 100으로 캡(모든 엔드포인트). 더 받으려면 `pageNo` 증가. 분석용 `fetch_all`은 `MAX_FETCH_ROWS=10000`까지 순회.
- **데이터 없음 = 정상응답**: `resultCode='00'` + `totalCount=0`(NODATA `03` 안 씀). 인증실패는 HTTP 401 `text/plain`.
- **위반건축물 필드 없음**: 표제부/기본개요/총괄표제부 어디에도 없음 → API로 조회 불가.
- **기본개요 컬럼 swap**: `translate_columns`가 `건축구분코드명`↔`건축구분코드`를 뒤바꿔 매핑 → 실제 명칭(신축/대수선)은 `건축구분코드`에, 코드값(0100)은 `건축구분코드명`에 들어옴. permits_pipeline은 `건축구분코드` 사용.
- **주택가격(공시가격) 시계열**: 호=`관리건축물대장PK`별로 `stdDay`(YYYY0101)+`주택가격`(원)이 연도별 행으로 쌓임. 집합건물은 호×연도라 fetch_all 필요. price_history가 PK 그룹·CAGR 산출.
- **철거멸실 석면·미래날짜오타**: `철거멸실관리대장`에 석면 함유(천장재/단열재/지붕재/보온재/바닥재/기타함유유무, '1'=함유). 컬럼명에 단위 포함(`연면적(㎡)`). 일부 행 철거시작일이 미래(2108 등) 오타 → demolitions는 정렬 시 미래날짜 강등.

## 주의

- 키는 `.env.local`(gitignore). 커밋/평문노출 금지. fly는 `fly secrets set`.
- 커밋 author는 `chrisryugj <ryuseungin@naver.com>` (gmail 금지). Co-Authored-By Claude 금지.
- 소유자 조회는 개인정보라 제외. 동 전체 조회는 무거우니 번지 지정 권장.
