"""同一试验下两份已保存切点方案的产率对比。

原则
----
* 仅对比 **同一试验**（同一条蒸馏曲线）下的方案：不同试验的产率数字
  不能直接相减（路由层负责校验，本模块假定已满足）。
* 体积%与质量%是两套计量基准：差值只在同一基准内计算（Δ = 方案B − 方案A），
  绝不把体积%与质量%交叉相减；两方案保存口径（basis）不同时给出提示。
* 数值取自各方案保存时的切点与结果快照（result_snapshot）；快照缺失时
  按当前试验数据重算并在 ``result_source`` 中标注。
* 馏分按名称对应（同名馏分按出现次序两两对应）；仅一方存在的馏分单独
  列出，不做减法。
"""
from __future__ import annotations

_W_TOL = 1e-9

# 总量对照行（体积基准与质量基准共用同一套键；质量基准缺项为 None）
TOTAL_ROW_SPEC: list[tuple[str, str]] = [
    ("nominal_yield_pct", "馏分名义产率之和（含重叠）"),
    ("union_yield_pct", "馏分并集产率（去重叠）"),
    ("overlap_pct", "其中：重叠量"),
    ("front_gap_pct", "前缺口"),
    ("inter_gap_pct", "中间缺口"),
    ("tail_gap_pct", "尾缺口"),
    ("uncut_distillate_pct", "范围内未切出馏出液"),
    ("light_unassigned_pct", "起点前回收（低于实测起点）"),
    ("residue_bottoms_gross_pct", "未回收残渣毛额（100−R_max，含损失/不凝气）"),
    ("residue_bottoms_pct", "扣除声明损失后的残渣净额"),
    ("residual_total_pct", "残余合计（未切出+起点前+未回收毛额）"),
    ("loss_pct", "其中声明：试验损失（已含在未回收毛额内）"),
    ("identity_sum_pct", "闭合合计（应=100%）"),
]

_BASIS_ZH = {"volume": "体积基准", "mass": "质量基准"}


def _delta(a, b):
    """B − A；任一侧缺数则不差减（不同基准/缺数据不直接相减）。"""
    if a is None or b is None:
        return None
    return round(float(b) - float(a), 4)


def _side(row: dict | None) -> dict | None:
    if row is None:
        return None
    return {
        "start_temp_c": row["start_temp_c"],
        "end_temp_c": row["end_temp_c"],
        "volume_yield_pct": row.get("volume_yield_pct"),
        "mass_yield_pct": row.get("mass_yield_pct"),
        "flags": list(row.get("flags") or []),
    }


def _keyed(rows: list[dict]) -> dict[tuple[str, int], dict]:
    """馏分名 -> （名称, 同名出现次序） -> 结果行，保证同名馏分稳定对应。"""
    seen: dict[str, int] = {}
    out: dict[tuple[str, int], dict] = {}
    for r in rows:
        name = str(r["name"])
        k = seen.get(name, 0)
        seen[name] = k + 1
        out[(name, k)] = r
    return out


def _change_desc(fa: dict | None, fb: dict | None) -> str:
    if fa is None:
        return "仅方案B有此馏分"
    if fb is None:
        return "仅方案A有此馏分"
    parts = []
    if abs(fa["start_temp_c"] - fb["start_temp_c"]) > _W_TOL:
        parts.append(f"初馏点 {fa['start_temp_c']:g}→{fb['start_temp_c']:g} ℃")
    if abs(fa["end_temp_c"] - fb["end_temp_c"]) > _W_TOL:
        parts.append(f"终馏点 {fa['end_temp_c']:g}→{fb['end_temp_c']:g} ℃")
    return "；".join(parts) if parts else "切点不变"


def _totals_rows(tot_a: dict | None, tot_b: dict | None) -> list[dict]:
    rows: list[dict] = []
    for key, label in TOTAL_ROW_SPEC:
        va = tot_a.get(key) if tot_a else None
        vb = tot_b.get(key) if tot_b else None
        rows.append({"key": key, "label": label, "a": va, "b": vb,
                     "delta": _delta(va, vb)})
    return rows


def build_comparison(
    *,
    experiment: dict,
    plan_a: dict,
    plan_b: dict,
    result_a: dict,
    result_b: dict,
    source_a: str,
    source_b: str,
) -> dict:
    """组装两份方案的对比结果（馏分差值 + 重叠/缺口/未回收量/提示并排）。"""
    notes: list[str] = [
        "差值 Δ = 方案B − 方案A，且只在同一计量基准内计算"
        "（体积%对体积%、质量%对质量%），两套基准绝不交叉相减",
    ]
    if plan_a["basis"] != plan_b["basis"]:
        notes.append(
            "两方案保存时的产率口径不同"
            f"（A={_BASIS_ZH.get(plan_a['basis'], plan_a['basis'])}，"
            f"B={_BASIS_ZH.get(plan_b['basis'], plan_b['basis'])}）："
            "对比仍按同基准列分别进行，解读时请注意各自口径"
        )
    if source_a != "snapshot" or source_b != "snapshot":
        notes.append(
            "存在缺少保存快照的方案，其数值已按当前试验数据重算（见 result_source）"
        )

    # ---- 馏分对照（按名称对应，缺侧不做减法）----
    rows_a = _keyed(result_a.get("cuts") or [])
    rows_b = _keyed(result_b.get("cuts") or [])
    keys = list(dict.fromkeys([*rows_a.keys(), *rows_b.keys()]))
    fractions: list[dict] = []
    changed: list[str] = []
    for name, occ in keys:
        sa = _side(rows_a.get((name, occ)))
        sb = _side(rows_b.get((name, occ)))
        endpoints: list[str] = []
        if sa is not None and sb is not None:
            if abs(sa["start_temp_c"] - sb["start_temp_c"]) > _W_TOL:
                endpoints.append("start")
            if abs(sa["end_temp_c"] - sb["end_temp_c"]) > _W_TOL:
                endpoints.append("end")
        dv = _delta(sa and sa["volume_yield_pct"], sb and sb["volume_yield_pct"])
        dm = _delta(sa and sa["mass_yield_pct"], sb and sb["mass_yield_pct"])
        interval_changed = bool(endpoints)
        yield_changed = (dv is not None and abs(dv) > _W_TOL) or (
            dm is not None and abs(dm) > _W_TOL
        )
        if (interval_changed or yield_changed or (sa is None) != (sb is None)) \
                and name not in changed:
            changed.append(name)
        fractions.append(
            {
                "name": name,
                "in_a": sa is not None,
                "in_b": sb is not None,
                "a": sa,
                "b": sb,
                "delta_volume_pct": dv,
                "delta_mass_pct": dm,
                "interval_changed": interval_changed,
                "changed_endpoints": endpoints,
                "change_desc": _change_desc(sa, sb),
            }
        )

    # ---- 总量与未回收量对照（体积基准必有，质量基准缺密度数据时为 None）----
    ta, tb = result_a.get("totals") or {}, result_b.get("totals") or {}
    ma, mb = ta.get("mass"), tb.get("mass")
    totals = {
        "volume": _totals_rows(ta, tb),
        "mass": _totals_rows(ma, mb) if (ma is not None or mb is not None) else None,
        "identity_ok": {"a": ta.get("identity_ok"), "b": tb.get("identity_ok")},
        "mass_identity": (
            {
                "a": {"ok": ma.get("identity_ok"), "note": ma.get("identity_note", "")}
                if ma else None,
                "b": {"ok": mb.get("identity_ok"), "note": mb.get("identity_note", "")}
                if mb else None,
            }
            if (ma is not None or mb is not None)
            else None
        ),
    }

    method = dict(result_a.get("method") or {})
    method["comparison"] = (
        "方案对比：Δ = 方案B − 方案A；仅同一试验内的方案可对比，"
        "体积%与质量%两套计量基准分别计算差值、不交叉相减；"
        "数值来自各方案保存时的切点与结果快照"
    )

    return {
        "experiment": {
            "id": experiment["id"],
            "name": experiment["name"],
            "sample_id": experiment.get("sample_id"),
        },
        "plan_a": plan_a,
        "plan_b": plan_b,
        "result_source": {"a": source_a, "b": source_b},
        "notes": notes,
        "fractions": fractions,
        "changed_fraction_names": changed,
        "overlaps": {
            "a": result_a.get("overlaps") or [],
            "b": result_b.get("overlaps") or [],
        },
        "gaps": {
            "a": result_a.get("gaps") or [],
            "b": result_b.get("gaps") or [],
        },
        "totals": totals,
        "issues": {
            "a": result_a.get("issues") or [],
            "b": result_b.get("issues") or [],
        },
        "applicable_range": result_a.get("applicable_range"),
        "method": method,
    }
