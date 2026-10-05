"""同一试验下两份**已保存**切点方案的对比。

铁律
----
* 只允许比较同一次离线试验的两份方案：曲线、密度表、进料密度必须相同，
  跨试验的产率数字没有相减的意义（端点处 R(T) 不同）；
* 差值只在**同一计量基准**内产生：体积% 只与体积% 相减，质量% 只与质量%
  相减，绝不拿体积基准数字去减质量基准数字；
* 双方各自使用保存时的切点（``Plan.cuts``）与**结果快照**
  （``Plan.result_snapshot``），重叠、缺口、越界等提示也按各自快照原样
  并排返回——一方越界不影响另一方提示的展示；
* 快照缺失（旧数据）时按保存切点重新计算，并在备注中注明。

配对
----
逐馏分按名称配对（同名多次出现按出现次序配对），名称对不上的馏分分别标为
"仅方案A/仅方案B"。调整一个切点时，除区间本身改变的馏分外，与之产生/消失
重叠、缺口相邻关系的馏分也一并标记为"受影响"。
"""
from __future__ import annotations

from collections import defaultdict

_TOL = 1e-6

# 总量行：(结果字典中的键, 教学用中文名, 是否属于用户输入项)
_TOTAL_VOLUME_ROWS = [
    ("nominal_yield_pct", "馏分名义产率之和（含重叠）", False),
    ("union_yield_pct", "馏分并集产率（去重叠）", False),
    ("overlap_pct", "其中：重叠量", False),
    ("front_gap_pct", "前缺口", False),
    ("inter_gap_pct", "中间缺口", False),
    ("tail_gap_pct", "尾缺口", False),
    ("uncut_distillate_pct", "范围内未切出馏出液", False),
    ("light_unassigned_pct", "起点前回收（低于实测起点）", False),
    ("residue_bottoms_gross_pct", "未回收残渣毛额（100−R_max，含损失/不凝气）", False),
    ("residue_bottoms_pct", "扣除声明损失后的残渣净额", False),
    ("identity_sum_pct", "闭合合计（应 = 100%）", False),
]
_TOTAL_INPUT_ROWS = [
    ("loss_pct", "声明试验损失（方案输入项，已含在残渣毛额内）", True),
]


def _occ_ids(rows: list[dict]) -> list[str]:
    """给每个馏分行生成'名称#第几次出现'的稳定标识。"""
    seen: dict[str, int] = defaultdict(int)
    ids: list[str] = []
    for r in rows:
        name = str(r["name"])
        occ = seen[name]
        seen[name] += 1
        ids.append(f"{name}#{occ}")
    return ids


def _diff(a, b):
    """b − a；任一侧缺数（None）则差值留空，绝不拿缺数凑差值。"""
    if a is None or b is None:
        return None
    return round(float(b) - float(a), 4)


def _relation_sets(snap: dict) -> tuple[set, set[str]]:
    """提取重叠/缺口关系键，以及参与到这些关系中的馏分名集合。"""
    rels: set = set()
    names: set[str] = set()

    def touch(nm) -> None:
        if nm:
            names.add(str(nm))

    for o in snap.get("overlaps") or []:
        key = (
            "overlap",
            str(o.get("cut_a_name")),
            str(o.get("cut_b_name")),
            round(float(o["from_temp_c"]), 2),
            round(float(o["to_temp_c"]), 2),
        )
        rels.add(key)
        touch(o.get("cut_a_name"))
        touch(o.get("cut_b_name"))
    for g in snap.get("gaps") or []:
        key = (
            f"gap:{g.get('kind')}",
            str(g.get("after_cut") or ""),
            str(g.get("before_cut") or ""),
            round(float(g["from_temp_c"]), 2),
            round(float(g["to_temp_c"]), 2),
        )
        rels.add(key)
        touch(g.get("after_cut"))
        touch(g.get("before_cut"))
    return rels, names


def _relations_diff(snap_a: dict, snap_b: dict) -> tuple[set, set[str]]:
    """返回 (仅单方存在的关系键, 受这些关系变化牵连的馏分名)。"""
    rels_a, names_a = _relation_sets(snap_a)
    rels_b, names_b = _relation_sets(snap_b)
    changed = (rels_a - rels_b) | (rels_b - rels_a)
    affected_names: set[str] = set()
    for key in changed:
        for token in key[1:3]:
            if token:
                affected_names.add(str(token))
    return changed, affected_names


def _totals_table(snap_a: dict, snap_b: dict, mass: bool) -> tuple[list[dict], dict | None]:
    """总量逐项并列与差值；mass=True 取 totals.mass（可能两侧都没有）。"""
    ta = snap_a.get("totals") or {}
    tb = snap_b.get("totals") or {}
    if mass:
        ma = ta.get("mass")
        mb = tb.get("mass")
        if ma is None or mb is None:
            return [], {
                "available": False,
                "note": "至少一份方案缺少密度/残渣密度数据，质量基准总量不完整，"
                        "质量总量差值留空（体积基准差值不受影响）",
            }
        src_a, src_b = ma, mb
    else:
        src_a, src_b = ta, tb

    rows_def = _TOTAL_VOLUME_ROWS + _TOTAL_INPUT_ROWS

    out: list[dict] = []
    for key, label, is_input in rows_def:
        if mass and key == "loss_pct" and key not in src_a:
            continue  # 质量块无此项则跳过（理论上存在）
        va = src_a.get(key)
        vb = src_b.get(key)
        out.append(
            {
                "key": key,
                "label": label,
                "is_input": is_input,
                "a_pct": va,
                "b_pct": vb,
                "delta_b_minus_a_pct": _diff(va, vb),
            }
        )
    note = mb.get("identity_note") or ma.get("identity_note") or None if mass else None
    return out, ({"available": True, "note": note} if mass else None)


def build_comparison(
    *,
    experiment: dict,
    plan_a: dict,
    snapshot_a: dict,
    plan_b: dict,
    snapshot_b: dict,
    snapshot_a_recomputed: bool = False,
    snapshot_b_recomputed: bool = False,
) -> dict:
    """构造两份方案的完整对比结构（纯函数，不触库）。

    plan_a/plan_b 至少含 id/name/basis/loss_pct/cuts；
    snapshot_* 为 evaluate_plan 的结果（保存快照或重算结果）。
    """
    notes: list[str] = []
    if snapshot_a_recomputed:
        notes.append(
            f"方案A「{plan_a['name']}」缺少保存时结果快照，表中A侧数字为按其保存切点"
            "与当前试验数据重新计算的结果"
        )
    if snapshot_b_recomputed:
        notes.append(
            f"方案B「{plan_b['name']}」缺少保存时结果快照，表中B侧数字为按其保存切点"
            "与当前试验数据重新计算的结果"
        )

    basis_labels = {"volume": "体积基准（进料体积 %）", "mass": "质量基准（进料质量 %）"}
    basis_mismatch = plan_a.get("basis") != plan_b.get("basis")
    if basis_mismatch:
        notes.append(
            "两份方案保存时选择的产率口径不同"
            f"（A：{basis_labels.get(plan_a.get('basis'), plan_a.get('basis'))}；"
            f"B：{basis_labels.get(plan_b.get('basis'), plan_b.get('basis'))}）。"
            "下表所有差值均为同基准内相减（体积−体积、质量−质量），"
            "未做任何跨基准相减"
        )
    # 通用口径声明由 comparison_rule 与导出固定文案承载，notes 只放方案特定提示

    cuts_a = snapshot_a.get("cuts") or []
    cuts_b = snapshot_b.get("cuts") or []
    ids_a = _occ_ids(cuts_a)
    ids_b = _occ_ids(cuts_b)

    # 按 occ-id 配对
    by_id_b = {i: k for k, i in enumerate(ids_b)}
    paired: list[dict] = []
    used_b: set[int] = set()
    for ia, cid in enumerate(ids_a):
        ib = by_id_b.get(cid)
        if ib is not None:
            used_b.add(ib)
        paired.append(
            _cut_pair(cid, cuts_a[ia], ia, cuts_b[ib] if ib is not None else None, ib)
        )
    for ib, cid in enumerate(ids_b):
        if ib in used_b:
            continue
        paired.append(_cut_pair(cid, None, None, cuts_b[ib], ib))

    # 关系（重叠/缺口）变化牵连
    _changed_rels, affected_names = _relations_diff(snapshot_a, snapshot_b)

    # 同名馏分出现多次时保守地把同名行都标为受影响
    name_counts: dict[str, int] = defaultdict(int)
    for row in paired:
        name_counts[str(row["name"])] += 1

    affected_cut_names: set[str] = set()
    for row in paired:
        own = row["pair_status"] != "matched" or row["endpoints_changed"]
        related = row["name"] in affected_names
        if related and name_counts[str(row["name"])] > 1:
            related = True  # 保守处理
        row["affected"] = bool(own or related)
        row["affected_reason"] = _reason(row, related)
        if row["affected"]:
            affected_cut_names.add(str(row["name"]))

    # 质量逐馏分差值是否可得（两份方案都算出了质量块）
    mass_cut_available = (
        (snapshot_a.get("totals") or {}).get("mass") is not None
        and (snapshot_b.get("totals") or {}).get("mass") is not None
    )

    volume_rows, _ = _totals_table(snapshot_a, snapshot_b, mass=False)
    mass_rows, mass_meta = _totals_table(snapshot_a, snapshot_b, mass=True)

    def severity_counts(snap: dict) -> dict:
        c = {"error": 0, "warning": 0, "info": 0}
        for it in snap.get("issues") or []:
            sev = it.get("severity")
            if sev in c:
                c[sev] += 1
        return c

    rng_a = snapshot_a.get("applicable_range") or {}
    rng_b = snapshot_b.get("applicable_range") or {}

    return {
        "comparison_rule": {
            "same_experiment_only": True,
            "delta_convention": "b_minus_a",
            "no_cross_basis_subtraction": True,
            "source": "saved_cuts_and_result_snapshots",
        },
        "experiment": {
            "id": experiment.get("id"),
            "name": experiment.get("name"),
            "sample_id": experiment.get("sample_id"),
        },
        "plans": {
            "a": _plan_header(plan_a, snapshot_a, snapshot_a_recomputed),
            "b": _plan_header(plan_b, snapshot_b, snapshot_b_recomputed),
        },
        "basis_mismatch": basis_mismatch,
        "applicable_range": rng_a or rng_b,
        "cuts": paired,
        "mass_cut_deltas_available": bool(mass_cut_available),
        "totals": {"volume": volume_rows, "mass": mass_rows, "mass_meta": mass_meta},
        "overlaps": {
            "a": snapshot_a.get("overlaps") or [],
            "b": snapshot_b.get("overlaps") or [],
        },
        "gaps": {
            "a": snapshot_a.get("gaps") or [],
            "b": snapshot_b.get("gaps") or [],
        },
        "issues": {
            "a": snapshot_a.get("issues") or [],
            "b": snapshot_b.get("issues") or [],
            "a_counts": severity_counts(snapshot_a),
            "b_counts": severity_counts(snapshot_b),
            "a_has_blocking_errors": bool(snapshot_a.get("has_blocking_errors")),
            "b_has_blocking_errors": bool(snapshot_b.get("has_blocking_errors")),
        },
        "affected_cut_names": sorted(affected_cut_names),
        "summary": {
            "cuts_a": len(cuts_a),
            "cuts_b": len(cuts_b),
            "overlaps_a": len(snapshot_a.get("overlaps") or []),
            "overlaps_b": len(snapshot_b.get("overlaps") or []),
            "gaps_a": len(snapshot_a.get("gaps") or []),
            "gaps_b": len(snapshot_b.get("gaps") or []),
        },
        "notes": notes,
    }


def _plan_header(plan: dict, snap: dict, recomputed: bool) -> dict:
    return {
        "id": plan.get("id"),
        "name": plan.get("name"),
        "basis": plan.get("basis"),
        "loss_pct": plan.get("loss_pct"),
        "cuts": plan.get("cuts") or [],
        "snapshot_recomputed": recomputed,
        "has_blocking_errors": bool(snap.get("has_blocking_errors")),
    }


def _cut_pair(
    cid: str,
    row_a: dict | None,
    ia: int | None,
    row_b: dict | None,
    ib: int | None,
) -> dict:
    if row_a is not None and row_b is not None:
        status = "matched"
        name = row_a.get("name")
        sa, ea = float(row_a["start_temp_c"]), float(row_a["end_temp_c"])
        sb, eb = float(row_b["start_temp_c"]), float(row_b["end_temp_c"])
        ds, de = round(sb - sa, 4), round(eb - ea, 4)
        endpoints_changed = abs(ds) > _TOL or abs(de) > _TOL
    elif row_a is not None:
        status = "only_a"
        name = row_a.get("name")
        ds = de = None
        endpoints_changed = False
    else:
        status = "only_b"
        name = (row_b or {}).get("name")
        ds = de = None
        endpoints_changed = False

    va = row_a.get("volume_yield_pct") if row_a else None
    vb = row_b.get("volume_yield_pct") if row_b else None
    ma = row_a.get("mass_yield_pct") if row_a else None
    mb = row_b.get("mass_yield_pct") if row_b else None

    return {
        "pair_id": cid,
        "name": name,
        "pair_status": status,
        "a_index": ia,
        "b_index": ib,
        "a": _brief_from_row(row_a),
        "b": _brief_from_row(row_b),
        "start_temp_delta_c": ds,
        "end_temp_delta_c": de,
        "endpoints_changed": endpoints_changed,
        "volume_yield_a_pct": va,
        "volume_yield_b_pct": vb,
        "volume_yield_delta_pct": _diff(va, vb),
        "mass_yield_a_pct": ma,
        "mass_yield_b_pct": mb,
        "mass_yield_delta_pct": _diff(ma, mb),
        "affected": False,  # 由调用方结合关系变化补全
        "affected_reason": "",
    }


def _brief_from_row(row: dict | None) -> dict | None:
    if row is None:
        return None
    return {
        "index": row.get("index"),
        "name": row.get("name"),
        "start_temp_c": row.get("start_temp_c"),
        "end_temp_c": row.get("end_temp_c"),
        "flags": row.get("flags", []),
        "volume_yield_pct": row.get("volume_yield_pct"),
        "mass_yield_pct": row.get("mass_yield_pct"),
    }


def _reason(row: dict, related: bool) -> str:
    reasons: list[str] = []
    if row["pair_status"] == "only_a":
        reasons.append("仅存在于方案A（B中已删除/改名）")
    elif row["pair_status"] == "only_b":
        reasons.append("仅存在于方案B（A中没有，新增/改名）")
    elif row["endpoints_changed"]:
        reasons.append("切点发生变化")
    if related:
        reasons.append("与其他馏分的重叠/缺口相邻关系发生变化")
    return "；".join(reasons)
