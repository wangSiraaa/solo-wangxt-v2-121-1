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


# ---- 方案对比导出 ----
_SRC_ZH = {"snapshot": "保存快照", "recomputed": "按当前数据重算"}
_BASIS_ZH = {"volume": "体积基准（进料体积 %）", "mass": "质量基准（进料质量 %）"}


def _fmt_signed(v, nd: int = 2) -> str:
    if v is None:
        return "—（数据不足）"
    return f"{v:+.{nd}f}"


def _side_range(s: dict | None) -> str:
    if s is None:
        return "—"
    return f"{s['start_temp_c']:g}~{s['end_temp_c']:g}"


def _side_yield(s: dict | None, key: str) -> str:
    if s is None:
        return "—"
    return _fmt(s.get(key))


def build_compare_markdown(cmp: dict) -> str:
    """两份方案的对比摘要（Markdown）。同样写明方法、适用范围与不外推声明。"""
    pa, pb = cmp["plan_a"], cmp["plan_b"]
    exp = cmp["experiment"]
    rng = cmp["applicable_range"]
    lines: list[str] = []
    lines.append(f"# 切点方案对比：{pa['name']} ⇄ {pb['name']}")
    lines.append("")
    lines.append(
        f"- 试验：{exp['name']}"
        + (f"（样品 {exp['sample_id']}）" if exp.get("sample_id") else "")
    )
    lines.append(f"- 导出时间（UTC）：{datetime.now(timezone.utc):%Y-%m-%d %H:%M:%S}")
    lines.append(
        f"- 方案A：{pa['name']}（{_BASIS_ZH.get(pa['basis'], pa['basis'])}，"
        f"声明损失 {pa['loss_pct']:g}%）"
    )
    lines.append(
        f"- 方案B：{pb['name']}（{_BASIS_ZH.get(pb['basis'], pb['basis'])}，"
        f"声明损失 {pb['loss_pct']:g}%）"
    )
    src = cmp.get("result_source") or {}
    lines.append(
        "- 数据来源：各方案保存的切点与结果快照"
        f"（A：{_SRC_ZH.get(src.get('a'), src.get('a'))}；"
        f"B：{_SRC_ZH.get(src.get('b'), src.get('b'))}）"
    )
    for n in cmp.get("notes") or []:
        lines.append(f"- 注意：{n}")
    lines.append("")

    lines.append("## 1. 方法与适用范围")
    m = cmp["method"]
    lines.append(f"- 插值方法：{m['interpolation']}")
    lines.append(f"- 曲线坐标：{m['recovery_axis']}")
    lines.append(f"- 质量/体积换算：{m['mass_conversion']}")
    lines.append(f"- 外推策略：{m['extrapolation']}")
    lines.append(f"- 对比规则：{m['comparison']}")
    lines.append(
        f"- 适用温度范围：{rng['temp_c'][0]:g} ~ {rng['temp_c'][1]:g} ℃；"
        f"对应回收 {rng['recovered_pct'][0]:g} ~ {rng['recovered_pct'][1]:g}%。"
        "范围外无数据、不外推。"
    )
    lines.append("")

    lines.append("## 2. 馏分产率对照（Δ = B − A，同基准相减）")
    lines.append(
        "| 馏分 | A 区间 ℃ | A 体积% | A 质量% | B 区间 ℃ | B 体积% | B 质量% "
        "| Δ体积% | Δ质量% | 切点变化 |"
    )
    lines.append(
        "|------|---------:|--------:|--------:|---------:|--------:|--------:"
        "|-------:|-------:|----------|"
    )
    for f in cmp["fractions"]:
        lines.append(
            f"| {f['name']} | {_side_range(f['a'])} | {_side_yield(f['a'], 'volume_yield_pct')} "
            f"| {_side_yield(f['a'], 'mass_yield_pct')} | {_side_range(f['b'])} "
            f"| {_side_yield(f['b'], 'volume_yield_pct')} | {_side_yield(f['b'], 'mass_yield_pct')} "
            f"| {_fmt_signed(f['delta_volume_pct'])} | {_fmt_signed(f['delta_mass_pct'])} "
            f"| {f['change_desc']} |"
        )
    lines.append("")
    changed = cmp.get("changed_fraction_names") or []
    lines.append(
        "**受影响馏分：** " + ("、".join(changed) if changed else "无（两方案切点与产率一致）")
    )
    lines.append("")

    lines.append("## 3. 总量与未回收量对照（Δ = B − A）")
    lines.append("")
    lines.append("**体积基准（进料体积 %）：**")
    lines.append("")
    lines.append("| 项目 | A | B | Δ |")
    lines.append("|------|---:|---:|---:|")
    for r in cmp["totals"]["volume"]:
        lines.append(
            f"| {r['label']} | {_fmt(r['a'])} | {_fmt(r['b'])} | {_fmt_signed(r['delta'])} |"
        )
    lines.append("")
    idok = cmp["totals"]["identity_ok"]
    lines.append(
        "体积基准闭合："
        f"A {'✅ 通过' if idok.get('a') else '❌ 不通过'}；"
        f"B {'✅ 通过' if idok.get('b') else '❌ 不通过'}"
    )
    lines.append("")
    if cmp["totals"].get("mass"):
        lines.append("**质量基准（进料质量 %）：**")
        lines.append("")
        lines.append("| 项目 | A | B | Δ |")
        lines.append("|------|---:|---:|---:|")
        for r in cmp["totals"]["mass"]:
            lines.append(
                f"| {r['label']} | {_fmt(r['a'])} | {_fmt(r['b'])} | {_fmt_signed(r['delta'])} |"
            )
        lines.append("")
        mi = cmp["totals"].get("mass_identity") or {}
        for tag, label in (("a", "A"), ("b", "B")):
            blk = mi.get(tag)
            if blk and blk.get("note"):
                lines.append(f"质量基准说明（方案{label}）：{blk['note']}")
        lines.append("")

    lines.append("## 4. 重叠与缺口（并排）")
    for tag, label in (("a", "A"), ("b", "B")):
        plan = pa if tag == "a" else pb
        lines.append(f"**方案{label}：{plan['name']}**")
        ovs = cmp["overlaps"][tag]
        if ovs:
            lines.append("")
            lines.append("重叠：")
            for o in ovs:
                lines.append(
                    f"- {o['cut_a_name']} × {o['cut_b_name']}："
                    f"{o['from_temp_c']:g}~{o['to_temp_c']:g} ℃"
                    f"（宽 {o['width_c']:g} ℃，{_fmt(o.get('volume_pct'))} 体积%，"
                    f"{_fmt(o.get('mass_pct'))} 质量%）"
                    + ("（部分在实测范围外）" if o["partial_outside_range"] else "")
                    + ("（完全在实测范围外）" if o["fully_outside_range"] else "")
                )
        else:
            lines.append("")
            lines.append("重叠：无。")
        gps = [g for g in cmp["gaps"][tag] if g["width_c"] > 0]
        if gps:
            lines.append("")
            lines.append("缺口：")
            kind_zh = {"front": "前缺口", "inter": "中间缺口", "tail": "尾缺口"}
            for gp in gps:
                lines.append(
                    f"- {kind_zh[gp['kind']]}：{gp['from_temp_c']:g}~{gp['to_temp_c']:g} ℃"
                    f"（宽 {gp['width_c']:g} ℃，{_fmt(gp.get('volume_pct'))} 体积%，"
                    f"{_fmt(gp.get('mass_pct'))} 质量%）"
                    + ("（范围外无数据）" if gp["fully_outside_range"] else "")
                )
        else:
            lines.append("")
            lines.append("缺口：无。")
        lines.append("")

    lines.append("## 5. 数据提示（并排，各自核实）")
    for tag, label in (("a", "A"), ("b", "B")):
        plan = pa if tag == "a" else pb
        lines.append(f"**方案{label}：{plan['name']}**")
        lines.append("")
        issues = cmp["issues"][tag]
        if issues:
            for it in issues:
                icon = {"error": "❌", "warning": "⚠️", "info": "ℹ️"}.get(it["severity"], "•")
                lines.append(f"- {icon} [{it['code']}] {it['message']}")
        else:
            lines.append("- ✅ 未发现数据与切点问题")
        lines.append("")

    lines.append("---")
    lines.append(
        "> 本对比仅基于给定的离线蒸馏试验数据，用于培训与产率核对，"
        "不用于控制真实装置。两方案同属同一试验；差值只在同一计量基准内计算；"
        "温度范围外不存在的高温数据一律未外推。"
    )
    return "\n".join(lines)


def to_compare_json(cmp: dict) -> str:
    return json.dumps(
        {
            "exported_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "scope_notice": (
                "仅基于给定离线试验数据，不控制真实装置；对比仅限同一试验内的两份方案，"
                "差值只在同一计量基准（体积%/质量%）内计算（Δ = B − A）；"
                "适用温度范围外不外推，不存在的高温数据未做任何假设。"
            ),
            "comparison": cmp,
        },
        ensure_ascii=False,
        indent=2,
        allow_nan=False,
    )
