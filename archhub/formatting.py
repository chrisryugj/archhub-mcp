"""조회 결과(DataFrame)를 LLM이 읽기 좋은 텍스트로 변환.

출처(국토교통부 건축HUB)를 항상 명시해 LLM이 데이터 근거를 사용자에게 전달하도록 한다.
"""

import datetime
from typing import Optional

import pandas as pd

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


def _area(v) -> Optional[str]:
    f = _num(v)
    return f"{f:,.2f}㎡" if f is not None else None


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
    parts.append("\n\n".join(building_card(row) for _, row in shown.iterrows()))
    parts.append("")
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
    age = datetime.date.today().year - year

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


def floors_to_text(df: pd.DataFrame, total: int, max_floors: int = 60) -> str:
    """층별개요를 층 스택(위→아래)으로. 한 층 여러 용도면 면적 합산해 나열."""
    d = df.copy()
    d["_area"] = pd.to_numeric(
        d.get("면적", pd.Series(dtype="object")).astype(str).str.replace(",", "").str.strip(),
        errors="coerce",
    ).fillna(0.0)
    d["_num"] = pd.to_numeric(d.get("층번호", pd.Series(dtype="object")), errors="coerce").fillna(0).astype(int)
    d["_gubun"] = d.get("층구분코드명", pd.Series(dtype="object")).astype(str).str.strip()

    floors = []
    for (gubun, num), grp in d.groupby(["_gubun", "_num"]):
        uses = grp.groupby(grp["주용도코드명"].astype(str).str.strip())["_area"].sum()
        uses = uses[uses.index != ""].sort_values(ascending=False)
        area_sum = float(grp["_area"].sum())
        label = f"지하{num}층" if gubun == "지하" else ("옥탑" if gubun == "옥탑" else f"{num}층")
        detail = " · ".join(f"{u} {a:,.0f}㎡" for u, a in uses.items())
        floors.append((_floor_sort_key(gubun, num), label, area_sum, detail))

    floors.sort(key=lambda r: r[0], reverse=True)  # 위층부터
    shown = floors[:max_floors]

    name = _g(d.iloc[0], "건물명") or _g(d.iloc[0], "동명칭") or ""
    header = f"■ 층별 구성 — {name}" if name else "■ 층별 구성"
    parts = [header, f"  총 {len(floors)}개 층 (행 {total}건)", ""]
    for _, label, area_sum, detail in shown:
        line = f"  {label:>5}  {area_sum:>9,.0f}㎡"
        if detail:
            line += f"  {detail}"
        parts.append(line)
    if len(floors) > max_floors:
        parts.append(f"  … {len(floors) - max_floors}개 층 생략 (max_floors로 조정)")
    parts.append("")
    parts.append(SOURCE)
    return "\n".join(parts)


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
