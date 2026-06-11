# Changelog

이 프로젝트의 주요 변경을 기록한다. 형식은 [Keep a Changelog](https://keepachangelog.com/ko/1.1.0/),
버전은 [SemVer](https://semver.org/lang/ko/)를 따른다.

## [0.3.0] - 2026-06-11

3차 프로덕션 리뷰 반영 + 신규 도구 `seismic_check`.

### 추가
- **`seismic_check`** — 내진설계 취약 추정 스캐너 (신규 API 0개, 표제부 재활용).
  한국 내진설계 의무화 연혁(1988 도입: 6층↑/10만㎡↑ → 1995 확대 → 2005: 3층↑/1,000㎡↑ →
  2015: 2층↑/500㎡↑ → 2017.12: 2층↑(목구조 3층↑)/200㎡↑ + 모든 주택)을 사용승인일 시점
  기준으로 적용해 '내진설계 미적용 추정' 건을 분류. 조적조·블록조 등 취약 구조 + 고층 순
  우선 점검 후보 제시. 연혁 규칙은 `SEISMIC_RULES`/`seismic_status()`로 분리(테스트 가능).
  면책 명시: 대장 기재 기준 추정 — 실제 내진성능은 구조안전진단으로만 확인 가능.

### 수정
- **`find_region` 정규식 크래시**: 검색어를 리터럴 매칭(`regex=False`)으로 — 괄호 등 정규식
  특수문자 입력 시 `re.error` 크래시 제거.
- **`building_floors` 다동 합산 버그**: 동명칭이 2개 이상인 필지는 동별 섹션으로 분리 —
  서로 다른 동의 같은 층이 한 줄로 합산되던 왜곡 수정. 주용도코드명 결측 방어 통일,
  기타용도 병기(예: 제2종근린생활시설(고시원)).
- **`permits_pipeline` 진행중 과대집계**: 허가 후 5년 경과 + 미착공 건을
  '장기 미착공(실효 가능성)'으로 분리 집계하고 해석 주의 경고를 명시. `since_year` 기본값을
  전체 → 최근 5년으로 변경(전체는 1900 등 과거 연도 지정).
- **`demolitions` 미래연도 오타**: 철거일 연도가 현재연도+1 초과면 since_year 필터를
  통과시키지 않고, 전체 조회 시 "(연도 오타 의심)" 표기.
- **컬럼 swap 의존 제거**: `permits_pipeline`의 건축구분 표기를 swap-detection 자가 보정
  (`_permit_kind` — 두 컬럼 중 숫자 코드값이 아닌 쪽을 명칭으로)으로 교체. PublicDataReader가
  swap을 고쳐도 안 깨지므로 `pyproject.toml`의 `<1.2` 상한 제거(requirements.txt 핀은 유지).
- **`page` 초과 명시 에러**: 100페이지 초과 요청을 조용한 클램프 대신 `INVALID_PARAMETER`로 거부.
- **전각 숫자 차단**: 지역코드 검증에 `isascii()` 동시 검사(전각 '１１２１５' 통과 방지).
- **`find_region` 구 단위 행 표시**: 읍면동·동리 모두 공백(시군구 단위) 행에
  "구 단위 — bdong_code로 사용 불가" 비고. 0건 시 행정동→법정동 재검색 안내 추가.

### 운영
- **응답 TTL 캐시**: `_request_page` 결과를 6시간 TTL + LRU(512항목) in-memory 캐시
  (표준 라이브러리 OrderedDict, 신규 의존성 없음). 빈 결과는 미캐시(일시 장애 고착 방지),
  캐시 히트는 일일 캡·api_calls 미산입.
- **`.env.local` 로드 시점**: import 시점 → `main()` 내부로 이동 — 테스트가 import만 해도
  `os.environ`이 변조되던 부작용 제거.
- **stderr 로깅**: 외부 API 호출 실패·일일 캡 도달·fetch_all 절단 3곳에 최소 로깅
  (stdout은 stdio MCP JSON-RPC라 무오염 유지).

### 테스트
- 단위테스트 65 → 95케이스. (regex 리터럴 매칭, 다동 층 분리, 장기 미착공 분리,
  swap 자가 보정 양방향, TTL 캐시 히트/만료/빈결과/LRU, page 초과, 전각 숫자,
  내진 규칙 경계연도 1988/2005/2015/2017.12, find_region 구 단위 표시 등)

## [0.2.1] - 2026-06-02

2차 프로덕션 리뷰(운영 정합성·건축 도메인 정확성) 반영.

### 성능
- **HTTP 연결 재사용**: `requests.Session`을 도입해 페이지 반복 호출(`fetch_all` 최대 100페이지)에
  keep-alive를 적용. 페이지당 TLS 핸드셰이크를 제거해 동 단위 도구(`district_stats`/`old_buildings`/
  `demolitions`/`permits_pipeline`)의 수집 속도를 개선. (60초 deadline 내 수집량 증가)

### 도메인 정확성
- **공시가격 ≠ 시세 경고**: `price_history` 출력 말미에 "공시가격은 시세가 아니며(통상 시세의 60~70%,
  연도별 현실화율 정책 변동 포함) 증감률·CAGR을 시세 상승률로 해석 금지" 경고를 명시.
- **다동 필지 건폐율/용적률 주석**: `building_profile`에서 여러 동이 있는 필지에 면적 계산값(`(계산)`)이
  쓰이면, 해당 값이 동 기준이며 필지 전체 합산이 아님을 명시.
- **노후 선별 누락 명시**: `old_buildings`가 사용승인일 미상/파싱불가로 제외한 건수를 결과 note에 표기.

### 환각 방어
- **`[NOT_FOUND]` 마커 일관화**: `price_history`가 행은 있으나 유효 가격(>0)·PK가 없어 필터 후 0건이 되는
  경로에서 평문 대신 `[NOT_FOUND]` + "추측 금지" 경고를 반환하도록 통일.

### 의존성 방어
- **PublicDataReader 상한**: `permits_pipeline`이 의존하는 `기본개요` 컬럼 swap(건축구분코드명↔건축구분코드)
  동작이 라이브러리 수정으로 깨질 때를 대비해 `pyproject.toml` 의존성에 `<1.2` 상한을 추가. swap 의존
  지점에 주석을 보강하고, swap 동작을 고정하는 회귀 테스트를 추가.

### 테스트
- 단위테스트 58 → 65케이스. (`price_history` 필터 후 빈 결과·시세 경고, `building_profile` 다동 주석,
  `permits_pipeline` swap 컬럼 고정 추가)

## [0.2.0] - 2026-06-02

건축 종사자용 도구 확장 + 프로덕션 하드닝 + 최초 fly.io 배포.

### 추가
- `building_profile` — 용도지역 포함 한 필지 종합카드(주용도·구조·규모·건폐율/용적률·세대·주차·승인·내진).
- `building_floors` — 층별 구성 스택(옥탑→지상→지하 용도·면적).
- `price_history` — 공시가격(주택가격) 호별 연도별 추이·총증감률·연평균상승률(CAGR).
- `district_stats` — 동 단위 통계(총괄·주용도별·연대별·노후도) + 규모 벤치마크(층수·용적률·높이 중앙값).
- `old_buildings` — 사용승인 경과연수 기준 노후건축물 선별.
- `demolitions` — 철거멸실관리대장 최근 철거순 + 석면 함유 부위 요약.
- `permits_pipeline` — 사용승인 전 진행중 인허가(착공/미착공 단계).

### 하드닝
- 직접 REST 호출(timeout/numOfRows/pageNo 제어), http→https 승격, 서비스키 마스킹.
- `fetch_all` 행/페이지/deadline 3중 상한, 법정동코드 캐시(stdout 무오염).
- 공용키 일일 호출 캡(`ARCHHUB_DAILY_CALL_CAP`), Bearer 인증 opt-in(`ARCHHUB_MCP_TOKEN`).
- 무인증 공개 remote 운영(claude.ai 웹 OAuth 한계), 단일 머신 세션 일관성.

[0.2.1]: https://github.com/chrisryugj/archhub-mcp/compare/v0.2.0...v0.2.1
[0.2.0]: https://github.com/chrisryugj/archhub-mcp/releases/tag/v0.2.0
