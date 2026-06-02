# 건축HUB MCP

**국토교통부 건축HUB 3개 API를 7개 도구로.** 건축물대장·건축인허가·주택인허가 + 법정동코드 조회 + **한 필지 종합카드** + **동 단위 통계 집계** + **노후건축물 분석**을 AI 어시스턴트에서 자연어로 바로.

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/Python-3.10+-blue.svg)](https://www.python.org)
[![FastMCP 3.x](https://img.shields.io/badge/FastMCP-3.x-green.svg)](https://github.com/jlowin/fastmcp)

> 국가법령정보 MCP가 "법령"을, 통계 MCP가 "통계"를 다루듯, 이건 **건축물 실체 데이터**를 다룬다.
> 건축물대장 · 건축인허가 · 주택인허가 — data.go.kr 공식 API 실측값만, 출처를 명시하고, 없으면 `[NOT_FOUND]`로 환각을 차단.

remote 커넥터(fly.io)에 **공용 인증키가 탑재**되어 있어, 사용자는 **URL만 등록하면** 키 발급 없이 바로 쓴다.

---

## 3개 킬러 기능

주소 한 줄이면 `find_region`으로 코드를 얻고, 그다음은 목적에 맞는 도구 하나로 끝난다.

### 1. `building_profile` — 한 필지 종합카드

표제부를 1콜 호출해 **주용도·구조·규모·건폐율/용적률·세대/주차·사용승인·내진·에너지효율**을 카드로 묶는다. `type_name`을 바꿔가며 여러 번 조회할 필요 없이, 건물 한 채의 전반을 한눈에. (중개·감정평가·건축 실무)

```
"자양동 아차산로 244 건물 정보 한눈에 보여줘"
→ building_profile(11215, 10500, bun=1, ji=1)
```

```
건축물 1개 동

■ (건물명 없음)
  위치: 서울특별시 광진구 아차산로 244 (자양동)
  용도: 판매시설 (기타: 사무실, 점포)  ·  구조: 철근콘크리트구조
  규모: 지상4/지하1층 · 높이 11.3m · 연면적 1,762.88㎡
  세대: 0세대 0가구 10호
  사용승인 1981-02-04

출처: 국토교통부 건축HUB (공공데이터포털 data.go.kr)
```

> 건폐율/용적률이 응답에 없으면 면적으로 직접 계산해 `(계산)` 표시 — 추정과 실측을 구분한다.

### 2. `district_stats` — 동 단위 건축물 통계

개별 건물이 아니라 **동 전체의 그림**이 필요할 때. 표제부 전체를 받아 총괄·주용도별·연대별·노후도 분포를 한 번에 집계한다. (도시계획·정비사업·지역분석)

```
"자양동 건축물 통계 내줘"
→ district_stats(11215, 10500)
```

```
[법정동 건축물 통계] 표제부 6057건 기준

■ 총괄
  총 6,057동 · 총 연면적 5,283,211㎡ · 평균 3.5층 · 평균 경과 33년

■ 주용도별 (상위 10)
  단독주택          3,543동 (58.5%) · 연면적 841,139㎡
  공동주택          1,346동 (22.2%) · 연면적 2,726,331㎡
  제1종근린생활시설       532동 ( 8.8%) · 연면적 280,975㎡
  ...

■ 사용승인 연대별
  1970s      814동 (13.4%)
  1980s    1,376동 (22.7%)
  1990s    2,094동 (34.6%)
  ...

■ 노후도 분포 (사용승인 경과연수)
  30~40년    2,563동 (42.3%)  ⚠
  40년 이상    1,551동 (25.6%)  ⚠
  → 경과 30년↑ 합계 4,114동 (67.9%)

출처: 국토교통부 건축HUB (공공데이터포털 data.go.kr)
```

### 3. `old_buildings` — 노후건축물 선별

동 전체 표제부에서 사용승인 경과연수를 계산해 노후 건물을 내림차순 정렬. **안전점검·정비사업 대상 1차 선별**에 바로 쓴다.

```
"자양동에서 40년 넘은 노후 건물 뽑아줘"
→ old_buildings(11215, 10500, min_age_years=40)
```

```
총 1551건 중 상위 30건 표시
표제부 6057건 중 경과 40년↑ 1551건 (경과연수 내림차순)

건물명  도로명대지위치   대지위치               주용도코드명  사용승인일   경과연수  연면적  지상층수  세대수
            서울특별시 광진구 자양동 268번지   단독주택  1924-07-20    102  16.53     1    0
            서울특별시 광진구 자양동 203번지   단독주택  1926-08-20    100  59.50     1    0
            ...
```

---

## 왜 만들었나

대한민국 모든 건물에는 **건축물대장**이 있다. 용도·구조·규모·사용승인일·건폐율·용적률·주차·내진까지 — 부동산 중개, 감정평가, 시공, 디벨로핑, 도시계획, 안전점검의 출발점이 전부 여기다. 이 데이터는 [건축HUB](https://cloud.eais.go.kr)와 [공공데이터포털](https://www.data.go.kr)에 공개돼 있지만, API는 영문 코드 컬럼·페이지네이션·인증키 등록으로 개발자조차 진입장벽이 높다.

이 프로젝트는 그 건축 데이터 시스템을 **7개 도구**로 감싸서, AI 어시스턴트나 스크립트에서 바로 호출할 수 있게 만든다. 코드 한 줄 모르는 실무자도 "자양동 노후건물 뽑아줘"라고 말하면 끝.

---

## 빠른 시작 (remote 커넥터)

공용키가 서버에 탑재돼 있어 **키 발급이 필요 없다.** URL만 등록하면 된다.

### Claude.ai 웹 (설치 없음)

설정 → **커넥터** → **커스텀 커넥터 추가** → URL에 입력:

```
https://archhub-mcp.fly.dev/mcp
```

추가 후 **구성 → 모든 도구 "항상 사용"**으로 설정하면, 채팅에서 "광진구 자양동 노후건물 알려줘"로 바로 사용.

### Claude Code

```bash
claude mcp add --transport http archhub https://archhub-mcp.fly.dev/mcp
```

### Claude Desktop / Cursor / Windsurf

원격 HTTP를 지원하는 클라이언트는 설정 파일 `mcpServers`에 추가:

```json
{
  "mcpServers": {
    "archhub": { "type": "http", "url": "https://archhub-mcp.fly.dev/mcp" }
  }
}
```

Claude Desktop은 원격 HTTP를 직접 못 붙이므로 `mcp-remote` 어댑터 경유 (Node.js 18+):

```json
{
  "mcpServers": {
    "archhub": { "command": "npx", "args": ["-y", "mcp-remote", "https://archhub-mcp.fly.dev/mcp"] }
  }
}
```

---

## 사용 예시

```
"광진구 자양동 법정동코드 알려줘"
 → find_region → sigungu=11215, bdong=10500

"자양동 1-1번지 건물 한눈에 보여줘"     → building_profile      # 종합카드
"자양동 건축물 통계 내줘"               → district_stats        # 동 단위 집계
"자양동 40년 넘은 노후 건물 뽑아줘"      → old_buildings         # 노후 선별
"자양동 1-1번지 표제부 원본 보여줘"      → building_ledger(표제부)  # 원천 데이터
```

> 주소는 먼저 `find_region`으로 `sigungu_code`/`bdong_code`를 얻은 뒤 다른 도구에 넘긴다. 큰 동은 번지(`bun`/`ji`) 지정 시 빠르다.

---

## 도구 (7개)

| 도구 | 설명 |
|------|------|
| `find_region` | 주소 키워드("광진구 자양동") → `sigungu_code`/`bdong_code` |
| `building_profile` | **한 필지 종합카드** — 주용도·구조·규모·건폐율/용적률·세대·주차·사용승인·내진·에너지 (중개·평가·건축) |
| `district_stats` | **동 단위 통계** — 총괄·주용도별·연대별·노후도 분포 집계 (도시계획·정비사업) |
| `old_buildings` | **노후건축물 분석** — 사용승인 경과연수 기준 정렬 (안전점검·정비사업 선별) |
| `building_ledger` | 건축물대장 10종 (기본개요·총괄표제부·표제부·층별개요·전유공용면적·주택가격 등) |
| `building_permit` | 건축인허가 17종 (기본개요·동별·층별·대수선·철거멸실·주차장 등) |
| `housing_permit` | 주택인허가 16종 (기본개요·동별·부대시설·관리공동 등) |

모든 응답은 공식 API 실측값이며 **출처를 명시**한다. 결과가 없으면 `[NOT_FOUND]`, 에러는 `[EXTERNAL_API_ERROR]` 등 머신 파싱 프리픽스 + "LLM은 추측 금지" 경고로 환각을 차단한다.

---

## 누가 쓰나

| 페르소나 | 주력 도구 | 시나리오 |
|---|---|---|
| **공무원·공공기관** | `district_stats` · `old_buildings` | 동 단위 노후도 집계, 정비사업·안전점검 대상 선별 |
| **건축사·시공** | `building_profile` · `building_permit` | 구조·규모·인허가 이력 즉시 확인 |
| **디벨로퍼** | `district_stats` · `old_buildings` | 지역 용도 구성·노후 분포로 사업성 1차 스크리닝 |
| **중개** | `building_profile` | 매물 건물 스펙 종합카드 한 장 |
| **감정평가** | `building_profile` · `building_ledger` | 면적·승인일·주차·세대, 주택가격 원천 조회 |

---

## 로컬 실행 (stdio)

원격 서버를 거치지 않고 직접 돌리려면 [data.go.kr 인증키](https://www.data.go.kr)가 필요하다 (건축HUB 서비스 활용신청 → 일반 인증키 Decoding).

```bash
git clone https://github.com/chrisryugj/archhub-mcp && cd archhub-mcp
pip install -e .                              # console_scripts 진입점 설치
export ARCHHUB_SERVICE_KEY="<디코딩 인증키>"   # Windows: set 또는 .env.local

archhub-mcp                                   # stdio 모드 (= python -m archhub)
archhub-mcp --transport http --port 8000      # http 모드
```

또는 설치 없이 `uvx`로:

```bash
ARCHHUB_SERVICE_KEY=... uvx --from . archhub-mcp
```

Claude Code 로컬 등록:

```bash
claude mcp add archhub -e ARCHHUB_SERVICE_KEY=<디코딩 키> -- archhub-mcp
```

`.env.local`에 키를 넣어두면 편하다 (`.env.example` 참고, git 커밋 제외됨).

---

## 테스트 · 개발

```bash
pip install -e ".[dev]"
pytest tests/        # 외부 API 비의존(네트워크 mock) · 37 케이스
```

응답파싱·키마스킹·카드 계산식·`fetch_all` 페이지절단 회귀·동단위 집계·키 만료 계산을 막는다.

---

## 배포 (fly.io)

```bash
fly launch --no-deploy                              # fly.toml 인식
fly secrets set ARCHHUB_SERVICE_KEY="<디코딩 키>"   # 공용키 주입 (평문 커밋 금지)
fly deploy
```

`auto_stop_machines=suspend` + `min_machines_running=0`로 무요청 시 0대까지 내려가 비용 절감, 요청 오면 자동 기동. `/health`는 버전·키 적재 여부·**키 만료 D-day**·프로세스 API 호출수를 노출한다.

---

## 데이터 출처 · 범위

- **출처**: 국토교통부 건축HUB (공공데이터포털 data.go.kr)
  - 건축물대장 `1613000/BldRgstHubService`
  - 건축인허가 `1613000/ArchPmsHubService`
  - 주택인허가 `1613000/HsPmsHubService`
- 영문 컬럼은 한글로 자동 변환 (PublicDataReader 매핑 재활용)
- 법정동코드 테이블은 런타임에 로드 후 캐시
- 동기 도구는 FastMCP가 워커 스레드풀로 위임 → http 동시요청에도 이벤트루프 비차단

## 한계 · 주의

- **공용키 트래픽 한도**: data.go.kr 개발계정은 일 10,000건 공유. 대량 사용 시 BYOK/운영계정 전환 권장. 정확한 잔여량은 API가 제공하지 않아 `/health`의 `api_calls`는 프로세스 단위 근사치.
- **위반건축물 조회 불가**: 표제부/기본개요/총괄표제부 어디에도 위반건축물 필드가 없음(실측 확인) → API로 조회 불가.
- **개인정보 제외**: 소유자(소유정보) 조회는 범위 밖.
- **동 전체 조회는 무거움**: 큰 동은 수천 건. `old_buildings`/`district_stats`는 전체를 받아 다소 느릴 수 있다. 페이지당 100건 고정이라 1만 행까지 순회 수집하며, 초과분은 응답에 절단을 명시한다.

---

## 라이선스

[MIT](LICENSE)

---

<sub>국토교통부 건축HUB 공개 데이터를 AI가 바로 읽도록 — Made by Chris</sub>
