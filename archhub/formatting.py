"""조회 결과(DataFrame)를 LLM이 읽기 좋은 텍스트로 변환.

출처(국토교통부 건축HUB)를 항상 명시해 LLM이 데이터 근거를 사용자에게 전달하도록 한다.
"""

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


def profile_to_text(df: pd.DataFrame, total: int, max_buildings: int, note: str = "") -> str:
    """필지의 표제부 행(동)들을 종합카드 묶음으로."""
    shown = df.head(max_buildings)
    header = f"건축물 {total}개 동"
    if total > max_buildings:
        header += f" 중 {max_buildings}개 표시 (max_buildings로 조정)"
    parts = [header]
    if note:
        parts.append(note)
    parts.append("")
    parts.append("\n\n".join(building_card(row) for _, row in shown.iterrows()))
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
