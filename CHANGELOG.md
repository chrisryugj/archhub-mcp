# Changelog

이 프로젝트의 주요 변경을 기록한다. 형식은 [Keep a Changelog](https://keepachangelog.com/ko/1.1.0/),
버전은 [SemVer](https://semver.org/lang/ko/)를 따른다.

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
