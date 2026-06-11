"""조회 결과(DataFrame)를 LLM이 읽기 좋은 텍스트로 변환.

출처(국토교통부 건축HUB)를 항상 명시해 LLM이 데이터 근거를 사용자에게 전달하도록 한다.
"""

import datetime
from typing import Optional

import pandas as pd

from .errors import not_found

SOURCE = "출처: 국토교통부 건축HUB (공공데이터포털 data.go.kr)"


def _num(v) -> Optional[float]:
    """문자열/숫자를 float로. 빈값·'0'·파싱불가는 None(미기재 취급)."""
    try:
        f = float(str(v).replace(",", "").strip())
    except (ValueError, TypeError):
        return None
    return f if f != 0 else None


def _g(row, col: str) -> Optional[str]:
    """행에서 컬럼값을 문자열로. 없거나 빈값/'nan'/'0'은 None."""
    if col not in row.index:
        return None
    s = str(row[col]).strip()
    if not s or s.lower() == "nan" or s == "0":
        return None
    return s


def _date(v) -> Optional[str]:
    """YYYYMMDD → YYYY-MM-DD. 아니면 None."""
    s = str(v).strip()
    if len(s) >= 8 and s[:8].isdigit():
        return f"{s[:4]}-{s[4:6]}-{s[6:8]}"
    return None


def _age_years(v, today: Optional[datetime.date] = None) -> Optional[int]:
    """사용승인일(YYYYMMDD 등) → 오늘 기준 만 경과연수. 파싱불가면 None.

    연도만 빼는 게 아니라 월·일까지 반영한다(승인일이 아직 안 지난 해는 1년 차감).
    예: 1996-12-31 승인 → 2026-06-02 기준 29년(아직 만 30년 아님)."""
    s = str(v).strip()
    if len(s) < 4 or not s[:4].isdigit():
        return None
    today = today or datetime.date.today()
    y = int(s[:4])
    m = int(s[4:6]) if len(s) >= 6 and s[4:6].isdigit() and 1 <= int(s[4:6]) <= 12 else 1
    d = int(s[6:8]) if len(s) >= 8 and s[6:8].isdigit() and 1 <= int(s[6:8]) <= 31 else 1
    age = today.year - y - ((today.month, today.day) < (m, d))
    return age if age >= 0 else None


def _area(v) -> Optional[str]:
    f = _num(v)
    return f"{f:,.2f}㎡" if f is not None else None


def _eok(v) -> Optional[str]:
    """원 단위 금액을 'N.NN억'으로. 빈값·0·파싱불가는 None."""
    f = _num(v)
    return f"{f / 1e8:.2f}억" if f is not None else None


def _year_of(v) -> Optional[int]:
    """YYYYMMDD/YYYY... 앞 4자리를 연도(int)로. 공백·비숫자는 None."""
    s = str(v).strip()
    return int(s[:4]) if len(s) >= 4 and s[:4].isdigit() else None


def building_card(row: pd.Series) -> str:
    """건축물대장 표제부 1행(동)을 사람이 읽기 좋은 종합카드 텍스트로."""
    name = _g(row, "건물명") or _g(row, "동명칭") or "(건물명 없음)"
    lines = [f"■ {name}"]

    loc = _g(row, "도로명대지위치") or _g(row, "대지위치")
    if loc:
        lines.append(f"  위치: {loc}")

    use = _g(row, "주용도코드명")
    etc = _g(row, "기타용도")
    struct = _g(row, "구조코드명")
    use_line = []
    if use:
        use_line.append(f"용도: {use}" + (f" (기타: {etc})" if etc else ""))
    if struct:
        use_line.append(f"구조: {struct}")
    if use_line:
        lines.append("  " + "  ·  ".join(use_line))

    up, down = _g(row, "지상층수"), _g(row, "지하층수")
    height = _num(row.get("높이"))
    gfa = _area(row.get("연면적"))
    land = _area(row.get("대지면적"))
    scale = []
    if up or down:
        scale.append(f"지상{up or 0}/지하{down or 0}층")
    if height:
        scale.append(f"높이 {height:g}m")
    if gfa:
        scale.append(f"연면적 {gfa}")
    if land:
        scale.append(f"대지 {land}")
    if scale:
        lines.append("  규모: " + " · ".join(scale))

    # 건폐율/용적률: 응답값 우선, 없으면 면적으로 계산(추정)
    bcr = _num(row.get("건폐율"))
    far = _num(row.get("용적률"))
    land_a, build_a = _num(row.get("대지면적")), _num(row.get("건축면적"))
    far_a = _num(row.get("용적률산정연면적"))
    ratio = []
    if bcr is not None:
        ratio.append(f"건폐율 {bcr:g}%")
    elif land_a and build_a:
        ratio.append(f"건폐율 {build_a / land_a * 100:.1f}%(계산)")
    if far is not None:
        ratio.append(f"용적률 {far:g}%")
    elif land_a and far_a:
        ratio.append(f"용적률 {far_a / land_a * 100:.1f}%(계산)")
    if ratio:
        lines.append("  " + " · ".join(ratio))

    se, ga, ho = _g(row, "세대수"), _g(row, "가구수"), _g(row, "호수")
    if se or ga or ho:
        lines.append(f"  세대: {se or 0}세대 {ga or 0}가구 {ho or 0}호")

    self_p = (_num(row.get("옥내자주식대수")) or 0) + (_num(row.get("옥외자주식대수")) or 0)
    mech_p = (_num(row.get("옥내기계식대수")) or 0) + (_num(row.get("옥외기계식대수")) or 0)
    if self_p or mech_p:
        lines.append(f"  주차: 자주식 {self_p:g}대 · 기계식 {mech_p:g}대")

    appr = _date(row.get("사용승인일"))
    perm = _date(row.get("허가일"))
    start = _date(row.get("착공일"))
    times = []
    if appr:
        times.append(f"사용승인 {appr}")
    if perm:
        times.append(f"허가 {perm}")
    if start:
        times.append(f"착공 {start}")
    if times:
        lines.append("  " + " · ".join(times))

    quake_y = _g(row, "내진 설계 적용 여부")
    quake_c = _g(row, "내진 능력")
    energy = _g(row, "에너지효율등급")
    extra = []
    if quake_y:
        extra.append(f"내진 {quake_y}" + (f"({quake_c})" if quake_c else ""))
    if energy:
        extra.append(f"에너지효율 {energy}등급")
    if extra:
        lines.append("  " + " · ".join(extra))

    return "\n".join(lines)


def profile_to_text(
    df: pd.DataFrame, total: int, max_buildings: int,
    note: str = "", zoning: Optional[str] = None,
) -> str:
    """필지의 표제부 행(동)들을 종합카드 묶음으로. zoning은 용도지역(법적 규제)."""
    shown = df.head(max_buildings)
    header = f"건축물 {total}개 동"
    if total > max_buildings:
        header += f" 중 {max_buildings}개 표시 (max_buildings로 조정)"
    parts = [header]
    if zoning:
        parts.append(f"용도지역·지구: {zoning}")  # 건축 규제의 출발점
    if note:
        parts.append(note)
    parts.append("")
    cards = "\n\n".join(building_card(row) for _, row in shown.iterrows())
    parts.append(cards)
    parts.append("")
    if total > 1 and "(계산)" in cards:
        # 건폐율/용적률 계산 fallback은 표제부 1행(동) 기준이라 다동 필지에서 필지 전체와 다를 수 있음
        parts.append("※ 여러 동이 있는 필지에서 건폐율/용적률 (계산) 값은 해당 동 기준이며 필지 전체 합산이 아닙니다(표제부 기재값 우선).")
    parts.append("※ 위반건축물 여부는 본 API에서 제공하지 않습니다(미표시가 '위반 없음'을 뜻하지 않음). 건축물대장 열람으로 별도 확인.")
    parts.append(SOURCE)
    return "\n".join(parts)


def _pct(n: int, total: int) -> str:
    return f"{(n / total * 100) if total else 0.0:4.1f}%"


def district_to_text(
    df: pd.DataFrame, total: int, trunc: str = "",
    min_age_years: int = 30, top_uses: int = 10,
) -> str:
    """법정동 표제부 전체를 받아 총괄·주용도별·연대별·노후도 분포로 집계."""
    n = len(df)
    area = pd.to_numeric(
        df.get("연면적", pd.Series(dtype="object")).astype(str).str.replace(",", "").str.strip(),
        errors="coerce",
    )
    floors = pd.to_numeric(df.get("지상층수", pd.Series(dtype="object")), errors="coerce")
    appr = df.get("사용승인일", pd.Series(dtype="object")).astype(str).str.strip()
    year = pd.to_numeric(appr.str[:4].where(appr.str.len() >= 4), errors="coerce")
    age = pd.to_numeric(appr.map(_age_years), errors="coerce")  # 월·일 반영 만 경과연수

    lines = [f"[법정동 건축물 통계] 표제부 {total}건{trunc} 기준", ""]

    # 총괄
    summary = [f"총 {n:,}동"]
    if area.notna().any():
        summary.append(f"총 연면적 {area.sum():,.0f}㎡")
    if floors.notna().any():
        summary.append(f"평균 {floors.mean():.1f}층")
    if age.notna().any():
        summary.append(f"평균 경과 {age.mean():.0f}년")
    lines.append("■ 총괄")
    lines.append("  " + " · ".join(summary))

    # 주용도별 (동수 상위)
    use = df.get("주용도코드명")
    if use is not None:
        u = use.astype(str).str.strip().replace({"": "(미상)", "nan": "(미상)"})
        grp = u.value_counts().head(top_uses)
        lines.append("")
        lines.append(f"■ 주용도별 (상위 {len(grp)})")
        for name, cnt in grp.items():
            a = area[u == name].sum() if area.notna().any() else 0
            asuf = f" · 연면적 {a:,.0f}㎡" if a else ""
            lines.append(f"  {name:<12} {cnt:>6,}동 ({_pct(cnt, n)}){asuf}")

    # 규모 벤치마크 (주용도별 층수·용적률·높이 중앙값 — 건축사 설계 참고)
    # 0은 미기재 취급(building_card와 동일) — 중앙값 왜곡 방지
    far = pd.to_numeric(
        df.get("용적률", pd.Series(dtype="object")).astype(str).str.replace(",", "").str.strip(),
        errors="coerce",
    ).replace(0, pd.NA)
    height = pd.to_numeric(df.get("높이", pd.Series(dtype="object")), errors="coerce").replace(0, pd.NA)
    floors_b = floors.replace(0, pd.NA)
    if use is not None and (floors_b.notna().any() or far.notna().any() or height.notna().any()):
        lines.append("")
        lines.append(f"■ 규모 벤치마크 (주용도별 · 중앙값, 상위 {len(grp)})")
        for name, cnt in grp.items():
            mask = (u == name)
            seg = []
            if floors_b[mask].notna().any():
                seg.append(f"지상 {floors_b[mask].median():.0f}층(최대 {floors_b[mask].max():.0f})")
            if far[mask].notna().any():
                seg.append(f"용적률 {far[mask].median():.0f}%")
            if height[mask].notna().any():
                seg.append(f"높이 {height[mask].median():.0f}m")
            if seg:
                lines.append(f"  {name:<12} {' · '.join(seg)}")

    # 사용승인 연대별
    if year.notna().any():
        decade = (year // 10 * 10).dropna().astype(int)
        lines.append("")
        lines.append("■ 사용승인 연대별")
        for dec in sorted(decade.unique()):
            cnt = int((decade == dec).sum())
            lines.append(f"  {dec}s   {cnt:>6,}동 ({_pct(cnt, n)})")
        unknown = int(year.isna().sum())
        if unknown:
            lines.append(f"  (미상) {unknown:>6,}동 ({_pct(unknown, n)})")

    # 노후도 분포
    if age.notna().any():
        bins = [(0, 10), (10, 20), (20, 30), (30, 40), (40, 200)]
        labels = ["10년 미만", "10~20년", "20~30년", "30~40년", "40년 이상"]
        lines.append("")
        lines.append("■ 노후도 분포 (사용승인 경과연수)")
        for (lo, hi), lab in zip(bins, labels):
            cnt = int(((age >= lo) & (age < hi)).sum())
            mark = "  ⚠" if lo >= min_age_years else ""
            lines.append(f"  {lab:<8} {cnt:>6,}동 ({_pct(cnt, n)}){mark}")
        unknown = int(age.isna().sum())
        if unknown:
            lines.append(f"  (미상)   {unknown:>6,}동 ({_pct(unknown, n)})")
        aged = int((age >= min_age_years).sum())
        lines.append(f"  → 경과 {min_age_years}년↑ 합계 {aged:,}동 ({_pct(aged, n)})")

    lines.append("")
    lines.append(SOURCE)
    return "\n".join(lines)


def _floor_sort_key(gubun: str, num: int) -> int:
    """층을 위→아래 순으로 정렬할 키. 옥탑 > 지상N > … > 지상1 > 지하1 > … 지하N."""
    if gubun == "옥탑":
        return 100000 + num
    if gubun == "지하":
        return -num
    return num


def _clean_str_col(d: pd.DataFrame, col: str) -> pd.Series:
    """컬럼을 공백 정리된 문자열 시리즈로. 없으면 빈 시리즈, 'nan'은 빈값 처리(결측 방어)."""
    if col not in d.columns:
        return pd.Series("", index=d.index)
    s = d[col].astype(str).str.strip()
    return s.mask(s.str.lower().isin(["nan", "none"]), "")


def _floor_use_labels(d: pd.DataFrame) -> pd.Series:
    """행별 용도 라벨. 기타용도가 있으면 주용도 옆에 병기 (예: 제2종근린생활시설(고시원))."""
    use = _clean_str_col(d, "주용도코드명")
    etc = _clean_str_col(d, "기타용도")
    out = use.copy()
    both = (use != "") & (etc != "") & (use != etc)
    out[both] = use[both] + "(" + etc[both] + ")"
    only_etc = (use == "") & (etc != "")
    out[only_etc] = etc[only_etc]
    return out


def _floor_stack(d: pd.DataFrame) -> list[tuple[int, str, float, str]]:
    """층별개요 행들을 (정렬키, 층라벨, 면적합, 용도상세) 목록으로. 위층부터 정렬."""
    floors = []
    for (gubun, num), grp in d.groupby(["_gubun", "_num"]):
        uses = grp.groupby(grp["_use"])["_area"].sum()
        uses = uses[uses.index != ""].sort_values(ascending=False)
        area_sum = float(grp["_area"].sum())
        label = f"지하{num}층" if gubun == "지하" else ("옥탑" if gubun == "옥탑" else f"{num}층")
        detail = " · ".join(f"{u} {a:,.0f}㎡" for u, a in uses.items())
        floors.append((_floor_sort_key(gubun, num), label, area_sum, detail))
    floors.sort(key=lambda r: r[0], reverse=True)  # 위층부터
    return floors


def _floor_lines(floors: list, max_floors: int, indent: str = "  ") -> list[str]:
    """층 스택을 출력 줄 목록으로 (max_floors 초과 시 생략 주석)."""
    lines = []
    for _, label, area_sum, detail in floors[:max_floors]:
        line = f"{indent}{label:>5}  {area_sum:>9,.0f}㎡"
        if detail:
            line += f"  {detail}"
        lines.append(line)
    if len(floors) > max_floors:
        lines.append(f"{indent}… {len(floors) - max_floors}개 층 생략 (max_floors로 조정)")
    return lines


def floors_to_text(df: pd.DataFrame, total: int, max_floors: int = 60) -> str:
    """층별개요를 층 스택(위→아래)으로. 한 층 여러 용도면 면적 합산해 나열.

    다동 필지(동명칭 2개 이상)는 동별 섹션으로 분리한다 — 동 구분 없이 층을 합산하면
    서로 다른 동의 같은 층이 한 줄로 합쳐져 면적·용도가 왜곡되기 때문.
    """
    d = df.copy()
    d["_area"] = pd.to_numeric(
        d.get("면적", pd.Series(dtype="object")).astype(str).str.replace(",", "").str.strip(),
        errors="coerce",
    ).fillna(0.0)
    d["_num"] = pd.to_numeric(d.get("층번호", pd.Series(dtype="object")), errors="coerce").fillna(0).astype(int)
    d["_gubun"] = d.get("층구분코드명", pd.Series(dtype="object")).astype(str).str.strip()
    d["_use"] = _floor_use_labels(d)
    d["_dong"] = _clean_str_col(d, "동명칭")

    dongs = [v for v in d["_dong"].unique() if v]
    if len(dongs) >= 2:
        # 다동: 동별 섹션 분리 (동명칭 없는 행은 '(동명칭 미상)'으로 묶음)
        name = _g(d.iloc[0], "건물명") or ""
        header = f"■ 층별 구성 — {name}" if name else "■ 층별 구성"
        groups = sorted(dongs)
        if (d["_dong"] == "").any():
            groups.append("")
        parts = [header, f"  동 {len(groups)}개 (행 {total}건)"]
        for dong in groups:
            sub = d[d["_dong"] == dong]
            floors = _floor_stack(sub)
            parts.append("")
            parts.append(f"  [{dong or '(동명칭 미상)'}] — {len(floors)}개 층")
            parts.extend(_floor_lines(floors, max_floors, indent="  "))
        parts.append("")
        parts.append(SOURCE)
        return "\n".join(parts)

    floors = _floor_stack(d)
    name = _g(d.iloc[0], "건물명") or _g(d.iloc[0], "동명칭") or ""
    header = f"■ 층별 구성 — {name}" if name else "■ 층별 구성"
    parts = [header, f"  총 {len(floors)}개 층 (행 {total}건)", ""]
    parts.extend(_floor_lines(floors, max_floors))
    parts.append("")
    parts.append(SOURCE)
    return "\n".join(parts)


def _sample_trend(points: list[tuple[int, float]], max_points: int = 6) -> str:
    """(연도, 가격) 리스트를 'YY N.NN억 → …' 추이 문자열로. 길면 최초·최신 포함 균등 샘플."""
    if len(points) > max_points:
        # 최초·최신은 항상, 사이는 균등 인덱스로 추림
        idx = sorted({0, len(points) - 1, *(round(i * (len(points) - 1) / (max_points - 1)) for i in range(max_points))})
        pts = [points[i] for i in idx]
    else:
        pts = points
    return " → ".join(f"'{y % 100:02d} {p / 1e8:.2f}억" for y, p in pts)


def price_history_to_text(
    df: pd.DataFrame, total: int, top_units: int, bun: str = "", ji: str = "",
) -> str:
    """주택가격(공시가격) 시계열을 호별로 묶어 추이·증감·연평균상승률로 요약.

    한 호(관리건축물대장PK)에 stdDay(YYYY0101 기준일)별 공시가격이 행으로 쌓여 있다.
    호별로 연도순 정렬해 최신가·최초→최신 추이·총증감률·연평균상승률(CAGR)을 낸다.
    호는 최신 공시가 내림차순으로 top_units개만 표시.
    """
    d = df.copy()
    d["_price"] = pd.to_numeric(
        d.get("주택가격", pd.Series(dtype="object")).astype(str).str.replace(",", "").str.strip(),
        errors="coerce",
    )
    d["_day"] = d.get("stdDay", pd.Series(dtype="object")).astype(str).str.strip()
    d["_year"] = pd.to_numeric(d["_day"].str[:4].where(d["_day"].str.len() >= 4), errors="coerce")
    d = d.dropna(subset=["_price", "_year"])
    d = d[d["_price"] > 0]
    if len(d) == 0 or "관리건축물대장PK" not in d.columns:
        # 행은 있었으나 유효 가격(>0)/PK가 없어 필터 후 0건 — 평문 대신 [NOT_FOUND]로
        # 환각 방어 경고를 붙인다(server의 len(df)==0 가로채기가 못 잡는 경로).
        return not_found(
            "공시가격(주택가격) 시계열 없음 (유효 가격 0건)",
            ["ji(부번) 조정", "공시가격이 없는 필지(비주거 등)일 수 있음"],
        )
    d["_year"] = d["_year"].astype(int)

    units = []  # (최신가, 라벨, 추이문자열, 요약문자열)
    for pk, sub in d.groupby("관리건축물대장PK"):
        sub = sub.sort_values("_year")
        pts = list(zip(sub["_year"].tolist(), sub["_price"].tolist()))
        # 같은 연도 중복은 마지막값으로 정리
        dedup: dict[int, float] = {}
        for y, p in pts:
            dedup[y] = p
        pts = sorted(dedup.items())
        y0, p0 = pts[0]
        y1, p1 = pts[-1]
        years = y1 - y0
        chg = (p1 - p0) / p0 * 100 if p0 else 0.0
        cagr = ((p1 / p0) ** (1 / years) - 1) * 100 if years > 0 and p0 > 0 else None
        addr = _g(sub.iloc[0], "새주소본번")
        addr_sub = _g(sub.iloc[0], "새주소부번")
        suffix = ""
        if addr:
            suffix = f" · 새주소 {addr}" + (f"-{addr_sub}" if addr_sub else "")
        label = f"호 PK…{str(pk)[-4:]}{suffix}"
        summary = f"최신 {p1 / 1e8:.2f}억 ({y1}) · 최초 {p0 / 1e8:.2f}억 ({y0}) · {years}년간 {chg:+.1f}%"
        if cagr is not None:
            summary += f" · 연평균 {cagr:+.1f}%"
        units.append((p1, label, _sample_trend(pts), summary))

    units.sort(key=lambda u: u[0], reverse=True)
    shown = units[:top_units]

    loc = f"{bun}-{ji}" if ji else (bun or "")
    head = f"[공시가격 시계열] {loc}".strip()
    lines = [f"{head} · 주택가격 {total}건 · {len(units)}호"]
    if len(units) > top_units:
        lines.append(f"최신 공시가 상위 {top_units}호 표시 (top_units로 조정)")
    lines.append("")
    for _, label, trend, summary in shown:
        lines.append(f"■ {label}")
        lines.append(f"  {summary}")
        lines.append(f"  추이: {trend}")
        lines.append("")
    lines.append("※ 공시가격은 시세가 아닙니다(통상 시세의 60~70% 수준, 연도별 현실화율 정책 변동 포함). "
                 "증감률·CAGR을 시세·실거래가 상승률로 해석하지 마세요.")
    lines.append(SOURCE)
    return "\n".join(lines)


# 철거멸실관리대장 석면(함유) 조사 컬럼 → 표시 라벨. 값 '1'=함유.
_ASBESTOS = {
    "천장재함유유무": "천장", "단열재함유유무": "단열", "지붕재함유유무": "지붕",
    "보온재함유유무": "보온", "바닥재함유유무": "바닥", "기타함유유무": "기타",
}


def demolitions_to_text(
    df: pd.DataFrame, total: int, trunc: str = "",
    since_year: Optional[int] = None, top: int = 30,
) -> str:
    """철거멸실관리대장을 최근 철거(시작일/멸실일) 순으로. 석면 함유 부위를 ⚠로 요약.

    철거 일정·연면적·용도·구조 + 석면(천장/단열/지붕/보온/바닥/기타) 함유 여부를 묶는다.
    석면은 철거 안전·비용에 직결되므로 함유 부위를 명시한다. (디벨로퍼·철거업체·공무원용)
    """
    d = df.copy()
    start = d.get("철거시작일", pd.Series(dtype="object")).astype(str).str.strip()
    demo = d.get("철거멸실일", pd.Series(dtype="object")).astype(str).str.strip()
    key = start.where(start.str.len() >= 8, demo)  # 시작일 우선, 없으면 멸실일
    d["_key"] = pd.to_numeric(key.str[:8].where(key.str.len() >= 8), errors="coerce").fillna(0)
    # 원본에 미래 날짜 오타(예 21080607)가 있어 '최근순' 1위를 먹는다 → 정렬상 뒤로 강등
    today_key = int(datetime.date.today().strftime("%Y%m%d"))
    d["_key"] = d["_key"].where(d["_key"] <= today_key, 0)
    d["_year"] = pd.to_numeric(key.str[:4].where(key.str.len() >= 4), errors="coerce")
    # 현재연도+1 초과는 연도 오타 의심 — since_year 필터를 '최근'으로 통과시키지 않고 표기만 남긴다
    d["_suspect"] = d["_year"] > (datetime.date.today().year + 1)
    if since_year is not None:
        d = d[(d["_year"] >= since_year) & ~d["_suspect"]]
    d = d.sort_values("_key", ascending=False)

    n = len(d)
    head = f"[철거멸실 현황] 철거멸실 {total}건{trunc}"
    if since_year is not None:
        head += f" 중 {since_year}년↑ {n}건"
    lines = [f"{head} (최근 철거순)"]
    if n > top:
        lines.append(f"상위 {top}건 표시 (top으로 조정)")
    lines.append("")

    for _, row in d.head(top).iterrows():
        loc = _g(row, "도로명대지위치") or _g(row, "대지위치") or "(위치 미상)"
        kind = _g(row, "철거멸실구분코드명")
        use = _g(row, "주용도코드명")
        struct = _g(row, "구조코드명")
        gfa = _area(row.get("연면적(㎡)"))
        s_d, e_d = _date(row.get("철거시작일")), _date(row.get("철거종료일"))
        m_d = _date(row.get("철거멸실일"))
        if s_d:
            period = f"철거 {s_d}~{e_d}" if e_d else f"철거 {s_d}~"
        elif m_d:
            period = f"멸실 {m_d}"
        else:
            period = "일자 미상"
        if bool(row.get("_suspect")):
            period += " (연도 오타 의심)"
        asb = [lab for col, lab in _ASBESTOS.items() if str(row.get(col, "")).strip() == "1"]
        asb_str = f" ⚠석면({'·'.join(asb)})" if asb else ""

        seg = [kind or "철거", use or "용도미상"]
        if struct:
            seg.append(struct)
        if gfa:
            seg.append(f"연면적 {gfa}")
        seg.append(period)
        lines.append(f"■ {loc}")
        lines.append(f"  {' · '.join(seg)}{asb_str}")

    lines.append("")
    lines.append(SOURCE)
    return "\n".join(lines)


# 허가 후 이 기간(년)이 지나도록 미착공이면 '장기 미착공'으로 분리한다.
# 건축법 제11조상 허가 후 일정 기간 내 미착공 시 허가가 취소(실효)될 수 있어,
# 수십 년 치 미착공 허가를 '진행중'으로 집계하면 공급 파이프라인이 과대평가된다.
STALE_PERMIT_YEARS = 5


def _permit_kind(row) -> Optional[str]:
    """건축구분(신축/증축/대수선 등) 명칭. 컬럼 swap 자가 보정.

    PublicDataReader 1.1.x의 translate_columns는 기본개요에서 건축구분코드명↔건축구분코드를
    뒤바꿔 매핑한다(실측) — 명칭이 '건축구분코드'에, 코드값(0100)이 '건축구분코드명'에 온다.
    어느 쪽이든 동작하도록 두 컬럼 중 값이 숫자(코드값)가 아닌 쪽을 명칭으로 쓴다.
    라이브러리가 swap을 고쳐도 깨지지 않는다.
    """
    for col in ("건축구분코드명", "건축구분코드"):
        v = _g(row, col)
        if v and not v.isdigit():
            return v
    return None


def pipeline_to_text(
    df: pd.DataFrame, total: int, trunc: str = "",
    since_year: Optional[int] = None, top: int = 30,
) -> str:
    """건축인허가 기본개요에서 '사용승인 전(진행중)' 건만 추려 허가일 최근순으로.

    단계: 실제착공일 有 = 착공, 空 = 미착공. (신규 공급 파이프라인 파악 — 디벨로퍼용)
    허가 후 STALE_PERMIT_YEARS년 경과 + 미착공 건은 실효 가능성이 높아 '장기 미착공'으로
    분리 집계한다(진행중 과대집계 방지).
    """
    d = df.copy()
    appr = d.get("사용승인일", pd.Series(dtype="object")).astype(str).str.strip()
    permit = d.get("건축허가일", pd.Series(dtype="object")).astype(str).str.strip()
    started = d.get("실제착공일", pd.Series(dtype="object")).astype(str).str.strip()
    has_appr = appr.str.len() >= 8
    has_permit = permit.str.len() >= 8
    d["_pkey"] = pd.to_numeric(permit.str[:8].where(has_permit), errors="coerce").fillna(0)
    d["_pyear"] = pd.to_numeric(permit.str[:4].where(permit.str.len() >= 4), errors="coerce")
    d["_started"] = started.str.len() >= 8
    prog = d[(~has_appr) & has_permit]  # 허가는 났고 사용승인 전 = 진행중 후보

    # 장기 미착공 분리: 허가 후 5년 경과 + 미착공 → 건축법상 허가 실효 가능성
    today = datetime.date.today()
    stale_cut = int(f"{today.year - STALE_PERMIT_YEARS}{today.month:02d}{today.day:02d}")
    stale_mask = (~prog["_started"]) & (prog["_pkey"] > 0) & (prog["_pkey"] < stale_cut)
    n_stale = int(stale_mask.sum())
    prog = prog[~stale_mask]
    if since_year is not None:
        prog = prog[prog["_pyear"] >= since_year]
    prog = prog.sort_values("_pkey", ascending=False)

    n = len(prog)
    head = f"[인허가 파이프라인] 기본개요 {total}건{trunc} 중 진행중(사용승인 전) {n}건"
    if since_year is not None:
        head += f" · 허가 {since_year}년↑"
    lines = [head]
    if n_stale:
        lines.append(f"장기 미착공(허가 {STALE_PERMIT_YEARS}년↑ 경과·실효 가능성) {n_stale}건은 진행중에서 분리(목록 미표시)")
    if n > top:
        lines.append(f"허가일 최근순 상위 {top}건 표시 (top으로 조정)")
    lines.append("")

    for _, row in prog.head(top).iterrows():
        loc = _g(row, "대지위치")
        name = _g(row, "건물명")
        title = (loc or "(위치 미상)") + (f" — {name}" if name else "")
        kind = _permit_kind(row)  # 신축/대수선 등 (swap 자가 보정)
        use = _g(row, "주용도코드명")
        gfa = _area(row.get("연면적(㎡)"))
        se = _g(row, "세대수(세대)")
        p_d = _date(row.get("건축허가일"))
        started = _date(row.get("실제착공일"))
        stage = "착공" if started else "미착공"

        scale = []
        if gfa:
            scale.append(f"연면적 {gfa}")
        if se:
            scale.append(f"{se}세대")
        seg = [s for s in [kind, use] if s]
        if scale:
            seg.append(" ".join(scale))
        if p_d:
            seg.append(f"허가 {p_d}")
        seg.append(f"단계: {stage}" + (f"({started})" if started else ""))
        lines.append(f"■ {title}")
        lines.append(f"  {' · '.join(seg)}")

    lines.append("")
    lines.append("※ 오래된 미착공 건은 건축법상 허가가 실효되었을 수 있음 — 진행중 수치 해석 주의.")
    lines.append(SOURCE)
    return "\n".join(lines)


# ---- 내진설계 의무화 연혁 (seismic_check) ----

# 건축법 시행령상 내진설계 의무 대상 기준의 변천 — 사용승인일 시점 기준으로 근사 판정.
# (시행시점 YYYYMMDD, 의무 최소 지상층수, 의무 최소 연면적㎡, 표기 라벨)
# 시행시점 이후 사용승인된 건물에 해당 기준을 적용한다. 1988-03 이전은 의무 자체가 없었다.
# 2017-12 개정은 특례가 있어 seismic_status()에서 별도 처리: 목구조 3층↑, 주택은 규모 무관 전부 의무.
SEISMIC_RULES = [
    (19880301, 6, 100_000, "1988(6층↑ 또는 10만㎡↑)"),
    (19950101, 6, 10_000, "1995(6층↑ 또는 1만㎡↑)"),
    (20050101, 3, 1_000, "2005(3층↑ 또는 1,000㎡↑)"),
    (20150101, 2, 500, "2015(2층↑ 또는 500㎡↑)"),
    (20171201, 2, 200, "2017.12(2층↑·목구조 3층↑ 또는 200㎡↑ + 모든 주택)"),
]
SEISMIC_PRE_1988 = "1988년 내진설계 의무화 이전 승인"

# 지진에 취약한 구조 키워드(구조코드명 부분일치) — 우선 점검 정렬에 사용
SEISMIC_VULNERABLE_STRUCTS = ("조적", "벽돌", "블록", "블럭", "석조", "흙")


def _vulnerable_struct(struct: str) -> bool:
    """조적조·벽돌조·블록조 등 지진 취약 구조 여부(구조코드명 부분일치)."""
    s = str(struct or "")
    return any(k in s for k in SEISMIC_VULNERABLE_STRUCTS)


def seismic_status(approval, floors, gfa, struct: str = "", use: str = "") -> tuple[str, str]:
    """사용승인일 시점의 내진설계 의무 기준으로 적용 여부를 추정한다.

    사용승인일 시점 의무 기준에 해당하지 않던 건물 = "미적용 추정"
    (준공 후 자발적 내진보강은 건축물대장으로 알 수 없음 — 보수적 추정).

    Args:
        approval: 사용승인일(YYYYMMDD 또는 YYYY…).
        floors: 지상층수.
        gfa: 연면적(㎡).
        struct: 구조코드명(목구조 특례 판정용).
        use: 주용도코드명(2017.12 주택 전면 의무 판정용).

    Returns:
        (판정, 근거) — 판정 ∈ {"의무 적용 추정", "미적용 추정", "판정 불가"}.
    """
    s = str(approval).strip()
    if len(s) < 4 or not s[:4].isdigit():
        return "판정 불가", "사용승인일 미상"
    # YYYYMMDD 비교키 (월·일 없으면 1월 1일로 간주)
    key = int(s[:8]) if len(s) >= 8 and s[:8].isdigit() else int(s[:4]) * 10000 + 101

    rule = None
    for eff, min_floors, min_area, label in SEISMIC_RULES:
        if key >= eff:
            rule = (eff, min_floors, min_area, label)
    if rule is None:
        return "미적용 추정", SEISMIC_PRE_1988

    eff, min_floors, min_area, label = rule
    if eff >= 20171201:
        if "주택" in str(use or ""):
            return "의무 적용 추정", f"{label} — 주택 전면 의무"
        if "목" in str(struct or ""):
            min_floors = 3  # 목구조 특례

    f, a = _num(floors), _num(gfa)
    if f is None and a is None:
        return "판정 불가", "층수·연면적 미상"
    if (f is not None and f >= min_floors) or (a is not None and a >= min_area):
        return "의무 적용 추정", f"{label} 기준 해당"
    return "미적용 추정", f"{label} 기준 미달"


def seismic_to_text(
    df: pd.DataFrame, total: int, trunc: str = "",
    min_floors: int = 3, max_buildings: int = 30,
) -> str:
    """표제부 전체에 내진 의무화 연혁 규칙을 적용해 '내진설계 미적용 추정' 건을 선별.

    ① 승인연도×층수×연면적으로 의무 적용 여부 추정 분류 ② 미적용 추정 + 지상 min_floors층↑
    건을 취약구조(조적조·블록조 등) 우선 → 고층 순으로 정렬해 상위 목록 제시.
    """
    n = len(df)
    counts = {"의무 적용 추정": 0, "미적용 추정": 0, "판정 불가": 0}
    pre1988 = 0
    unapplied: list[tuple[bool, float, pd.Series, str]] = []  # (취약구조, 층수, 행, 근거)
    for _, row in df.iterrows():
        struct = _g(row, "구조코드명") or ""
        status, basis = seismic_status(
            row.get("사용승인일", ""), row.get("지상층수"), row.get("연면적"),
            struct=struct, use=_g(row, "주용도코드명") or "",
        )
        counts[status] += 1
        if status != "미적용 추정":
            continue
        if basis == SEISMIC_PRE_1988:
            pre1988 += 1
        f = _num(row.get("지상층수"))
        if f is not None and f >= min_floors:
            unapplied.append((_vulnerable_struct(struct), f, row, basis))

    lines = [f"[내진설계 취약 추정 스캔] 표제부 {total}건{trunc} 기준", ""]
    lines.append(
        f"미적용 추정 {counts['미적용 추정']:,}건 / 전체 {n:,}동 "
        f"(의무 적용 추정 {counts['의무 적용 추정']:,}건 · 판정 불가 {counts['판정 불가']:,}건)"
    )
    if pre1988:
        lines.append(f"└ 미적용 추정 중 1988년 의무화 이전 승인 {pre1988:,}건")
    lines.append("")

    unapplied.sort(key=lambda t: (t[0], t[1]), reverse=True)  # 취약구조 우선 → 고층 순
    lines.append(f"우선 점검 후보: 미적용 추정 + 지상 {min_floors}층↑ {len(unapplied):,}건 (취약구조 → 고층 순)")
    if len(unapplied) > max_buildings:
        lines.append(f"상위 {max_buildings}건 표시 (max_buildings로 조정)")
    if not unapplied:
        lines.append("(해당 없음 — min_floors를 낮추면 소규모 건물까지 포함)")
    lines.append("")

    for vuln, f, row, basis in unapplied[:max_buildings]:
        loc = _g(row, "도로명대지위치") or _g(row, "대지위치") or "(위치 미상)"
        name = _g(row, "건물명") or _g(row, "동명칭")
        struct = _g(row, "구조코드명") or "구조 미상"
        appr = _date(row.get("사용승인일"))
        seg = [struct + (" ⚠취약구조" if vuln else ""), f"지상 {f:g}층"]
        if appr:
            seg.append(f"승인 {appr}")
        else:
            y = _year_of(row.get("사용승인일", ""))
            if y:
                seg.append(f"승인 {y}년")
        seg.append(f"근거: {basis}")
        lines.append(f"■ {loc}" + (f" — {name}" if name else ""))
        lines.append(f"  {' · '.join(seg)}")

    lines.append("")
    lines.append(
        "※ 건축물대장 기재(사용승인일·층수·연면적·구조) 기준 추정입니다 — 실제 내진성능은 "
        "구조안전진단으로만 확인 가능합니다. 내진보강 이력은 대장에 미반영될 수 있고, "
        "'의무 적용 추정'이 실제 내진성능 확보를 보증하지 않습니다."
    )
    lines.append(SOURCE)
    return "\n".join(lines)


def df_to_text(df: Optional[pd.DataFrame], max_rows: int = 50, note: str = "") -> str:
    """DataFrame을 '총 N건 + 표 + 출처' 텍스트로. 빈 결과는 errors.not_found 권장."""
    if df is None or len(df) == 0:
        return "조회 결과 없음 (0건)\n\n" + SOURCE
    total = len(df)
    shown = df.head(max_rows)
    header = f"총 {total}건"
    if total > max_rows:
        header += f" 중 상위 {max_rows}건 표시 (전체가 필요하면 max_rows를 늘리세요)"
    parts = [header]
    if note:
        parts.append(note)
    parts.append("")
    parts.append(shown.to_string(index=False))
    parts.append("")
    parts.append(SOURCE)
    return "\n".join(parts)
