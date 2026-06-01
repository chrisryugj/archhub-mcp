# 건축HUB MCP

국토교통부 **건축HUB**(공공데이터포털)의 건축 데이터를 자연어로 조회하는 MCP 서버.
국가법령정보 MCP가 "법령"을, 통계 MCP가 "통계"를 다루듯, 이건 **건축물 실체 데이터**를 다룬다.

> 건축물대장 · 건축인허가 · 주택인허가 + 법정동코드 조회 + 노후건축물 분석

remote 커넥터(fly.io)에 **공용 인증키가 탑재**되어 있어, 사용자는 **URL만 등록하면** 바로 쓴다.

---

## 도구

| 도구 | 설명 |
|------|------|
| `find_region` | 주소 키워드("광진구 자양동") → `sigungu_code`/`bdong_code` |
| `building_profile` | **한 필지 종합카드** — 주용도·구조·규모·건폐율/용적률·세대·주차·사용승인·내진·에너지효율을 1콜로 (중개·평가·건축 실무) |
| `building_ledger` | 건축물대장 10종 (기본개요·총괄표제부·표제부·층별개요·전유공용면적·주택가격 등) |
| `building_permit` | 건축인허가 17종 (기본개요·동별·층별·대수선·철거멸실·주차장 등) |
| `housing_permit` | 주택인허가 16종 |
| `old_buildings` | 동 단위 노후건축물 분석 — 사용승인 경과연수 기준 정렬 (안전점검·정비사업 대상 선별) |

모든 응답은 공식 API 실측값이며 **출처를 명시**한다. 결과가 없으면 `[NOT_FOUND]`로 표시해
LLM이 데이터를 지어내지 않도록 한다.

---

## 빠른 시작 (remote 커넥터)

### Claude Code
```bash
claude mcp add --transport http archhub https://archhub-mcp.fly.dev/mcp
```

### Claude Desktop
설정 → Connectors → **Add custom connector** → URL에 `https://archhub-mcp.fly.dev/mcp` 입력.

키 입력 불필요 (서버에 공용키 탑재).

---

## 사용 예시

```
"광진구 자양동 법정동코드 알려줘"
 → find_region → sigungu=11215, bdong=10500

"자양동 1-1번지 건물 정보 한눈에 보여줘"
 → building_profile(11215, 10500, bun=1, ji=1)   # 종합카드

"자양동 1-1번지 건물 표제부 원본 보여줘"
 → building_ledger(표제부, 11215, 10500, bun=1, ji=1)

"자양동에서 30년 넘은 노후 건물 30개 뽑아줘"
 → old_buildings(11215, 10500, min_age_years=30)
```

---

## 로컬 실행 (stdio)

```bash
pip install -r requirements.txt
export ARCHHUB_SERVICE_KEY="<data.go.kr 일반 인증키(Decoding)>"   # Windows: set 또는 .env.local
python -m archhub                 # stdio 모드
python -m archhub --transport http --port 8000   # http 모드
```

Claude Code 로컬 등록:
```bash
claude mcp add archhub -- python -m archhub
# (ARCHHUB_SERVICE_KEY 환경변수 필요)
```

`.env.local` 에 키를 넣어두면 편하다 (`.env.example` 참고, git 커밋 제외됨).

---

## 테스트

```bash
pip install -r requirements-dev.txt
pytest tests/        # 외부 API 비의존(네트워크 mock) · 29 케이스
```

응답파싱·키마스킹·카드 계산식·`fetch_all` 페이지절단 회귀를 막는다.

---

## 배포 (fly.io)

```bash
fly launch --no-deploy                              # fly.toml 인식
fly secrets set ARCHHUB_SERVICE_KEY="<디코딩 키>"   # 공용키 주입 (평문 커밋 금지)
fly deploy
```

`auto_stop_machines=suspend` + `min_machines_running=0` 로 무요청 시 0대까지 내려가 비용 절감,
요청 오면 자동 기동.

---

## 데이터 출처 · 범위

- **출처**: 국토교통부 건축HUB (공공데이터포털 data.go.kr)
  - 건축물대장 `1613000/BldRgstHubService`
  - 건축인허가 `1613000/ArchPmsHubService`
  - 주택인허가 `1613000/HsPmsHubService`
- 영문 컬럼은 한글로 자동 변환 (PublicDataReader 매핑 재활용)
- 법정동코드 테이블은 런타임에 로드 후 캐시

## 한계 · 주의

- **공용키 트래픽 한도**: data.go.kr 개발계정은 일 10,000건 공유. 대량 사용 시 BYOK/운영계정 전환 필요.
- **개인정보 제외**: 소유자(소유정보) 조회는 MVP 범위 밖.
- **동 전체 조회는 무거움**: 큰 동은 수천 건. 번지(`bun`/`ji`) 지정 시 빠름. `old_buildings`는 전체를 받아 다소 느릴 수 있음.

## 라이선스

MIT
