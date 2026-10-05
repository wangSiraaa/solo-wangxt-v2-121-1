"""方案导出：Markdown 与 JSON。

每份导出都必须写明：插值方法、密度换算依据、温度适用范围、“不外推”声明。
"""
from __future__ import annotations

import json
from datetime import datetime, timezone


def _fmt(v, nd: int = 2) -> str:
    if v is None:
        return "—（数据不足）"
    return f"{v:.{nd}f}"


def build_markdown(exp: dict, plan: dict, result: dict) -> str:
    rng = result["applicable_range"]
    totals = result["totals"]
    basis_name = "质量基准（进料质量 %）" if plan["basis"] == "mass" else "体积基准（进料体积 %）"
    lines: list[str] = []
    lines.append(f"# 蒸馏切割方案：{plan['name']}")
    lines.append("")
    lines.append(f"- 试验：{exp['name']}" + (f"（样品 {exp['sample_id']}）" if exp.get("sample_id") else ""))
    lines.append(f"- 导出时间（UTC）：{datetime.now(timezone.utc):%Y-%m-%d %H:%M:%S}")
    lines.append(f"- 当前产率口径：{basis_name}")
    cond = exp.get("conditions") or {}
    if cond:
        lines.append("- 试验条件：" + "；".join(f"{k}={v}" for k, v in cond.items()))
    lines.append(
        f"- 进料密度（20 ℃）：{exp['feed_density_g_cm3']:.3f} g/cm³"
    )
    lines.append("")

    lines.append("## 1. 方法与适用范围")
    m = result["method"]
    lines.append(f"- 插值方法：{m['interpolation']}")
    lines.append(f"- 曲线坐标：{m['recovery_axis']}")
    lines.append(f"- 质量/体积换算：{m['mass_conversion']}")
    lines.append(f"- 外推策略：{m['extrapolation']}")
    lines.append(
        f"- 适用温度范围：{rng['temp_c'][0]:g} ~ {rng['temp_c'][1]:g} ℃；"
        f"对应回收 {rng['recovered_pct'][0]:g} ~ {rng['recovered_pct'][1]:g}%"
    )
    lines.append(
        "  低于下限的轻端、高于上限的高温段均**无数据、不外推**；"
        "请通过补充离线试验点扩大适用范围。"
    )
    lines.append(f"- 总量核对式：{m['identity']}")
    lines.append("")

    lines.append("## 2. 馏分切点与产率")
    lines.append("| # | 馏分 | 初馏点 ℃ | 终馏点 ℃ | 体积产率 % | 质量产率 % | 标记 |")
    lines.append("|---|------|---------:|---------:|----------:|----------:|------|")
    for c in result["cuts"]:
        flags = "、".join(_FLAG_ZH.get(f, f) for f in c["flags"]) or ""
        lines.append(
            f"| {c['index'] + 1} | {c['name']} | {c['start_temp_c']:g} | {c['end_temp_c']:g} | "
            f"{_fmt(c['volume_yield_pct'])} | {_fmt(c['mass_yield_pct'])} | {flags} |"
        )
    lines.append("")

    lines.append("## 3. 重叠、缺口与残余")
    if result["overlaps"]:
        lines.append("**重叠（同一温度段被重复计入产率）：**")
        for o in result["overlaps"]:
            lines.append(
                f"- {o['cut_a_name']} × {o['cut_b_name']}："
                f"{o['from_temp_c']:g}~{o['to_temp_c']:g} ℃"
                f"（宽 {o['width_c']:g} ℃，{_fmt(o.get('volume_pct'))} 体积%，"
                f"{_fmt(o.get('mass_pct'))} 质量%）"
                + ("（部分在实测范围外）" if o["partial_outside_range"] else "")
                + ("（完全在实测范围外）" if o["fully_outside_range"] else "")
            )
    else:
        lines.append("**重叠：** 无。")
    lines.append("")
    if result["gaps"]:
        lines.append("**缺口（温度段可蒸出但未被馏分覆盖）：**")
        kind_zh = {"front": "前缺口（低于首切点）", "inter": "中间缺口", "tail": "尾缺口（高于末切点）"}
        for g in result["gaps"]:
            lines.append(
                f"- {kind_zh[g['kind']]}：{g['from_temp_c']:g}~{g['to_temp_c']:g} ℃"
                f"（宽 {g['width_c']:g} ℃，{_fmt(g.get('volume_pct'))} 体积%，"
                f"{_fmt(g.get('mass_pct'))} 质量%）"
            )
    lines.append("")
    lines.append("**总量核对（体积基准，进料=100%）：**")
    lines.append("")
    lines.append("| 项目 | 体积 % | 质量 % |")
    lines.append("|------|------:|------:|")
    rows = [
        ("馏分名义产率之和（含重叠）", totals["nominal_yield_pct"], _m(totals, "nominal_yield_pct")),
        ("馏分并集产率（去重叠）", totals["union_yield_pct"], _m(totals, "union_yield_pct")),
        ("其中：重叠量", totals["overlap_pct"], _m(totals, "overlap_pct")),
        ("前缺口", totals["front_gap_pct"], _m(totals, "front_gap_pct")),
        ("中间缺口", totals["inter_gap_pct"], _m(totals, "inter_gap_pct")),
        ("尾缺口", totals["tail_gap_pct"], _m(totals, "tail_gap_pct")),
        ("范围内未切出馏出液", totals["uncut_distillate_pct"], _m(totals, "uncut_distillate_pct")),
        ("起点前回收（低于实测起点）", totals["light_unassigned_pct"], _m(totals, "light_unassigned_pct")),
        ("未回收残渣毛额（100−R_max，含损失/不凝气）", totals["residue_bottoms_gross_pct"], _m(totals, "residue_bottoms_gross_pct")),
        ("其中：扣除声明损失后的残渣净额", totals["residue_bottoms_pct"], _m(totals, "residue_bottoms_pct")),
        ("残余合计（未切出+起点前+未回收毛额）", totals["residual_total_pct"], _m(totals, "residual_total_pct")),
        ("其中声明：试验损失（已含在未回收毛额内）", totals["loss_pct"], totals["loss_pct"]),
        ("闭合合计（应=100%）", totals["identity_sum_pct"], _m(totals, "identity_sum_pct")),
    ]
    for name, v, mv in rows:
        lines.append(f"| {name} | {_fmt(v)} | {_fmt(mv)} |")
    lines.append("")
    lines.append(
        f"体积基准闭合：{'通过（=100%）' if totals['identity_ok'] else '不通过：残差 ' + str(totals['identity_residual_pct']) + '%'}"
    )
    mb = totals.get("mass")
    if mb and mb.get("identity_note"):
        lines.append(f"质量基准说明：{mb['identity_note']}")
    lines.append("")

    if result["issues"]:
        lines.append("## 4. 数据与切点提示（请核实）")
        for it in result["issues"]:
            icon = {"error": "❌", "warning": "⚠️", "info": "ℹ️"}.get(it["severity"], "•")
            lines.append(f"- {icon} [{it['code']}] {it['message']}")
        lines.append("")

    lines.append("---")
    lines.append(
        "> 本方案仅基于给定的离线蒸馏试验数据，用于培训与产率核对，"
        "不用于控制真实装置。温度范围外不存在的高温数据一律未外推。"
    )
    return "\n".join(lines)


_FLAG_ZH = {
    "out_of_range": "切点越界",
    "clipped_to_range": "已按实测范围截断",
    "zero_width": "零宽（相邻切点相等）",
    "inverted": "区间反向",
}


def _m(totals: dict, key: str):
    mb = totals.get("mass")
    return mb.get(key) if mb else None


def build_json_payload(exp: dict, plan: dict, result: dict) -> dict:
    return {
        "exported_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "scope_notice": (
            "仅基于给定离线试验数据，不控制真实装置；"
            "适用温度范围外不外推，不存在的高温数据未做任何假设。"
        ),
        "experiment": exp,
        "plan": plan,
        "result": result,
    }


def to_json(exp: dict, plan: dict, result: dict) -> str:
    return json.dumps(
        build_json_payload(exp, plan, result), ensure_ascii=False, indent=2, allow_nan=False
    )


# ---- 两份已保存方案对比导出 ----
def _cfmt(v, nd: int = 2) -> str:
    """对比表用的简短缺数显示（区别于单方案导出的'数据不足'长文本）。"""
    if v is None:
        return "—"
    return f"{v:.{nd}f}"


def _cmp_delta(v, nd: int = 2) -> str:
    if v is None:
        return "—"
    if abs(v) <= 5e-5:
        return f"0.00（无变化）"
    return f"{v:+.{nd}f}"


def _cmp_temp_delta(v) -> str:
    if v is None:
        return ""
    if abs(v) <= 1e-6:
        return "0"
    return f"{v:+g}"


def _cmp_flags(flags: list[str]) -> str:
    return "、".join(_FLAG_ZH.get(f, f) for f in (flags or []))


def build_comparison_markdown(exp: dict, cmp: dict) -> str:
    """同试验两方案对比摘要：逐馏分并列+差值、重叠/缺口/未回收并排、双方提示。"""
    pa, pb = cmp["plans"]["a"], cmp["plans"]["b"]
    basis_name = {"volume": "体积%", "mass": "质量%"}
    lines: list[str] = []
    lines.append(f"# 切割方案对比摘要：{pa['name']}（A） vs {pb['name']}（B）")
    lines.append("")
    lines.append(f"- 试验：{exp['name']}"
                 + (f"（样品 {exp['sample_id']}）" if exp.get("sample_id") else ""))
    lines.append(f"- 导出时间（UTC）：{datetime.now(timezone.utc):%Y-%m-%d %H:%M:%S}")
    lines.append(
        f"- 方案A：#{pa['id']} {pa['name']}，保存口径 {basis_name.get(pa['basis'], pa['basis'])}"
        + ("，结果为重算" if pa.get("snapshot_recomputed") else "，使用保存时结果快照")
    )
    lines.append(
        f"- 方案B：#{pb['id']} {pb['name']}，保存口径 {basis_name.get(pb['basis'], pb['basis'])}"
        + ("，结果为重算" if pb.get("snapshot_recomputed") else "，使用保存时结果快照")
    )
    rng = cmp.get("applicable_range") or {}
    if rng.get("temp_c"):
        lines.append(
            f"- 同一试验、同一曲线（{rng['temp_c'][0]:g}~{rng['temp_c'][1]:g} ℃）"
            "与同一套密度/进料数据"
        )
    lines.append("")

    lines.append("## 1. 对比口径声明")
    lines.append("- 差值一律为 **方案B − 方案A**；两份方案来自**同一次离线试验**。")
    lines.append(
        "- 体积产率差值只在**体积基准内**相减，质量产率差值只在**质量基准内**相减；"
        "体积%与质量%是两套计量基准，**不跨基准相减**。"
    )
    lines.append(
        "- 切点超出实测温度范围的部分按各自方案标记（切点越界/已截断），"
        "越界部分无数据、不外推；两方案的越界提示分别保留。"
    )
    if cmp.get("basis_mismatch"):
        lines.append(
            "- ⚠️ 两份方案保存时选择的产率口径不同，体积列与质量列仍各自按同基准相减，"
            "请勿把一方的体积%与另一方的质量%直接比较。"
        )
    for n in cmp.get("notes", []):
        lines.append(f"- 备注：{n}")
    lines.append("")

    lines.append("## 2. 逐馏分：切点与产率差值（受影响馏分以 ★ 标出）")
    lines.append(
        "| 状态 | 馏分 | A 区间 ℃ | B 区间 ℃ | 切点变化(初/终) ℃ | "
        "A 体积% | B 体积% | Δ体积% | A 质量% | B 质量% | Δ质量% | A 标记 | B 标记 |"
    )
    lines.append(
        "|---|------|---------|---------|------------------|"
        "-------:|-------:|------:|-------:|-------:|------:|------|------|"
    )
    status_zh = {"matched": "配对", "only_a": "仅A", "only_b": "仅B"}
    for r in cmp["cuts"]:
        star = "★ " if r.get("affected") else ""
        a, b = r.get("a"), r.get("b")

        def iv(side):
            if not side:
                return "（无此馏分）"
            return f"{side['start_temp_c']:g}~{side['end_temp_c']:g}"

        change = ""
        if r["pair_status"] == "matched":
            ds, de = r.get("start_temp_delta_c"), r.get("end_temp_delta_c")
            if (ds is not None and abs(ds) > 1e-6) or (de is not None and abs(de) > 1e-6):
                change = f"初 {_cmp_temp_delta(ds)} / 终 {_cmp_temp_delta(de)}"
            else:
                change = "切点相同"
        lines.append(
            f"| {status_zh[r['pair_status']]} | {star}{r['name']} | {iv(a)} | {iv(b)} | {change} | "
            f"{_cfmt(None if not a else a['volume_yield_pct'])} | "
            f"{_cfmt(None if not b else b['volume_yield_pct'])} | "
            f"{_cmp_delta(r.get('volume_yield_delta_pct'))} | "
            f"{_cfmt(None if not a else a['mass_yield_pct'])} | "
            f"{_cfmt(None if not b else b['mass_yield_pct'])} | "
            f"{_cmp_delta(r.get('mass_yield_delta_pct'))} | "
            f"{_cmp_flags(a['flags']) if a else ''} | {_cmp_flags(b['flags']) if b else ''} |"
        )
    lines.append("")
    if cmp.get("affected_cut_names"):
        lines.append(
            "受影响馏分：" + "、".join(cmp["affected_cut_names"])
            + "（含切点改变，或与其他馏分的重叠/缺口相邻关系发生变化）"
        )
        lines.append("")

    lines.append("## 3. 总量与未回收量并排（体积基准，进料=100%）")
    lines.append("| 项目 | 方案A 体积% | 方案B 体积% | Δ（B−A） |")
    lines.append("|------|----------:|----------:|--------:|")
    for row in cmp["totals"]["volume"]:
        prefix = "（输入项）" if row.get("is_input") else ""
        lines.append(
            f"| {prefix}{row['label']} | {_cfmt(row['a_pct'], 4)} | "
            f"{_cfmt(row['b_pct'], 4)} | {_cmp_delta(row['delta_b_minus_a_pct'], 4)} |"
        )
    lines.append("")

    mass_rows = cmp["totals"].get("mass") or []
    mass_meta = cmp["totals"].get("mass_meta")
    if mass_rows:
        lines.append("## 4. 总量并排（质量基准，进料=100%）")
        lines.append("| 项目 | 方案A 质量% | 方案B 质量% | Δ（B−A） |")
        lines.append("|------|----------:|----------:|--------:|")
        for row in mass_rows:
            prefix = "（输入项）" if row.get("is_input") else ""
            lines.append(
                f"| {prefix}{row['label']} | {_cfmt(row['a_pct'], 4)} | "
                f"{_cfmt(row['b_pct'], 4)} | {_cmp_delta(row['delta_b_minus_a_pct'], 4)} |"
            )
        if mass_meta and mass_meta.get("note"):
            lines.append("")
            lines.append(f"质量基准说明：{mass_meta['note']}")
        lines.append("")
    else:
        lines.append(
            f"## 4. 质量基准总量：不可用——{(mass_meta or {}).get('note', '质量数据不完整')}"
        )
        lines.append("")

    lines.append("## 5. 重叠 / 缺口并排")
    ov_a, ov_b = cmp["overlaps"]["a"], cmp["overlaps"]["b"]
    lines.append(f"- 重叠：方案A {len(ov_a)} 处；方案B {len(ov_b)} 处。")
    for tag, ovs in (("A", ov_a), ("B", ov_b)):
        for o in ovs:
            scope = ("部分在实测范围外" if o.get("partial_outside_range")
                     else "完全在实测范围外" if o.get("fully_outside_range") else "范围内")
            lines.append(
                f"  - [{tag}] {o['cut_a_name']} × {o['cut_b_name']}："
                f"{o['from_temp_c']:g}~{o['to_temp_c']:g} ℃"
                f"（宽 {o['width_c']:g} ℃，{_cfmt(o.get('volume_pct'))} 体积%，"
                f"{_cfmt(o.get('mass_pct'))} 质量%，{scope}）"
            )
    kind_zh = {"front": "前缺口", "inter": "中间缺口", "tail": "尾缺口"}
    gp_a, gp_b = cmp["gaps"]["a"], cmp["gaps"]["b"]
    lines.append(f"- 缺口：方案A {len(gp_a)} 段；方案B {len(gp_b)} 段。")
    for tag, gps in (("A", gp_a), ("B", gp_b)):
        for g in gps:
            scope = ("范围外（无数据）" if g.get("fully_outside_range")
                     else "部分越界" if g.get("partial_outside_range") else "范围内")
            where = " → ".join(
                x for x in (g.get("after_cut"), g.get("before_cut")) if x
            ) or "—"
            lines.append(
                f"  - [{tag}] {kind_zh[g['kind']]}（{where}）："
                f"{g['from_temp_c']:g}~{g['to_temp_c']:g} ℃"
                f"（宽 {g['width_c']:g} ℃，{_cfmt(g.get('volume_pct'))} 体积%，"
                f"{_cfmt(g.get('mass_pct'))} 质量%，{scope}）"
            )
    lines.append("")

    lines.append("## 6. 数据与切点提示（双方各自保留，并排）")
    for tag, side in (("A", pa), ("B", pb)):
        issues = cmp["issues"][{"A": "a", "B": "b"}[tag]]
        cnt = cmp["issues"][{"A": "a_counts", "B": "b_counts"}[tag]]
        lines.append(
            f"### 方案{tag}「{side['name']}」"
            f"（错误 {cnt['error']}、需核实 {cnt['warning']}、提示 {cnt['info']}）"
        )
        if not issues:
            lines.append("- ✅ 无提示。")
        for it in issues:
            icon = {"error": "❌", "warning": "⚠️", "info": "ℹ️"}.get(it["severity"], "•")
            lines.append(f"- {icon} [{it['code']}] {it['message']}")
        lines.append("")

    lines.append("---")
    lines.append(
        "> 本对比仅基于同一次离线蒸馏试验的两份已保存方案（含保存时结果快照），"
        "用于教学讲解切点调整对产率、重叠、缺口与未回收量的影响；"
        "不同试验、不同计量基准的数字未直接相减。温度范围外不外推。"
    )
    return "\n".join(lines)


def comparison_to_json(exp: dict, cmp: dict) -> str:
    payload = {
        "exported_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "scope_notice": (
            "同一离线试验下两份已保存方案的对比；差值为方案B−方案A，"
            "体积/质量各自同基准相减，不跨试验、不跨计量基准；"
            "适用温度范围外不外推。"
        ),
        "experiment": {
            "id": exp.get("id"),
            "name": exp.get("name"),
            "sample_id": exp.get("sample_id"),
        },
        "comparison": cmp,
    }
    return json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False)
