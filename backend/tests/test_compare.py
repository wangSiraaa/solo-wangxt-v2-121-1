"""方案对比：同试验限定、馏分差值定位、并排提示与对比导出。"""
from __future__ import annotations

import pytest

# 曲线 30~400 ℃、回收 0~95%（留 5% 未回收残渣）；段中点 65/150/250/350 ℃
# 均被密度表覆盖，质量基准可用。
EXP_PAYLOAD = {
    "name": "对比用试验",
    "feed_density_g_cm3": 0.8,
    "residue_density_g_cm3": 0.95,
    "points": [
        {"temp_c": 30, "recovered_pct": 0},
        {"temp_c": 100, "recovered_pct": 20},
        {"temp_c": 200, "recovered_pct": 50},
        {"temp_c": 300, "recovered_pct": 80},
        {"temp_c": 400, "recovered_pct": 95},
    ],
    "density_rows": [
        {"temp_c": 60, "density_g_cm3": 0.70},
        {"temp_c": 150, "density_g_cm3": 0.78},
        {"temp_c": 250, "density_g_cm3": 0.85},
        {"temp_c": 350, "density_g_cm3": 0.90},
    ],
}

CUTS_BASE = [
    {"name": "轻", "start_temp_c": 30, "end_temp_c": 100},
    {"name": "中", "start_temp_c": 100, "end_temp_c": 200},
    {"name": "重", "start_temp_c": 200, "end_temp_c": 400},
]
# 只调整「中」的终馏点 200 → 250（其余切点不动）
CUTS_ONE_MOVED = [
    {"name": "轻", "start_temp_c": 30, "end_temp_c": 100},
    {"name": "中", "start_temp_c": 100, "end_temp_c": 250},
    {"name": "重", "start_temp_c": 200, "end_temp_c": 400},
]


def _mk_experiment(client, name="对比用试验") -> int:
    payload = dict(EXP_PAYLOAD, name=name)
    r = client.post("/api/experiments", json=payload)
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _save_plan(client, exp_id, cuts, name="p", basis="volume", loss=0.0) -> int:
    r = client.post(
        f"/api/experiments/{exp_id}/plans",
        json={"name": name, "basis": basis, "loss_pct": loss, "cuts": cuts},
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _compare(client, pa, pb, expect=200):
    r = client.get(f"/api/compare?plan_a={pa}&plan_b={pb}")
    assert r.status_code == expect, r.text
    return r.json() if expect == 200 else r


def test_single_cut_change_localizes_affected_fraction(client):
    exp = _mk_experiment(client)
    pa = _save_plan(client, exp, CUTS_BASE, name="基准方案")
    pb = _save_plan(client, exp, CUTS_ONE_MOVED, name="调整方案", loss=2.0)
    cmp = _compare(client, pa, pb)

    # 只动了一个切点 => 只有「中」被定位受影响（初/终馏点变化被标出）
    assert cmp["changed_fraction_names"] == ["中"]
    fr = {f["name"]: f for f in cmp["fractions"]}
    assert fr["中"]["interval_changed"] and fr["中"]["changed_endpoints"] == ["end"]
    assert "终馏点 200→250" in fr["中"]["change_desc"]
    assert not fr["轻"]["interval_changed"] and fr["轻"]["delta_volume_pct"] == 0
    assert not fr["重"]["interval_changed"] and fr["重"]["delta_volume_pct"] == 0

    # Δ = B − A，与各自保存快照中的产率一致（体积、质量分别计算）
    assert fr["中"]["delta_volume_pct"] == pytest.approx(
        fr["中"]["b"]["volume_yield_pct"] - fr["中"]["a"]["volume_yield_pct"], abs=1e-4
    )
    assert fr["中"]["delta_volume_pct"] > 0
    assert fr["中"]["delta_mass_pct"] == pytest.approx(
        fr["中"]["b"]["mass_yield_pct"] - fr["中"]["a"]["mass_yield_pct"], abs=1e-4
    )

    # 「中」终馏点右移后与「重」在 200~250 ℃ 产生重叠：仅出现在方案B侧
    assert cmp["overlaps"]["a"] == []
    assert len(cmp["overlaps"]["b"]) == 1
    assert cmp["overlaps"]["b"][0]["from_temp_c"] == 200

    # 总量并排：同一曲线 => 未回收毛额相同；损失不同 => 残渣净额差 −2
    rows = {r["key"]: r for r in cmp["totals"]["volume"]}
    assert rows["residue_bottoms_gross_pct"]["a"] == 5.0
    assert rows["residue_bottoms_gross_pct"]["b"] == 5.0
    assert rows["residue_bottoms_gross_pct"]["delta"] == 0
    assert rows["residue_bottoms_pct"]["delta"] == pytest.approx(-2.0)
    assert rows["overlap_pct"]["delta"] > 0
    # 质量基准对照同样给出
    assert cmp["totals"]["mass"] is not None
    # 数值来自保存快照
    assert cmp["result_source"] == {"a": "snapshot", "b": "snapshot"}


def test_compare_rejects_different_experiments(client):
    e1 = _mk_experiment(client, "对比-试验1")
    e2 = _mk_experiment(client, "对比-试验2")
    p1 = _save_plan(client, e1, CUTS_BASE)
    p2 = _save_plan(client, e2, CUTS_BASE)
    r = _compare(client, p1, p2, expect=422)
    assert "不同试验" in r.json()["detail"]["message"]


def test_compare_rejects_same_plan_and_missing_plan(client):
    exp = _mk_experiment(client)
    pa = _save_plan(client, exp, CUTS_BASE)
    assert _compare(client, pa, pa, expect=422).status_code == 422
    assert _compare(client, pa, 999999, expect=404).status_code == 404


def test_out_of_range_issues_kept_side_by_side(client):
    exp = _mk_experiment(client)
    pa = _save_plan(
        client, exp, [{"name": "越界A", "start_temp_c": 350, "end_temp_c": 450}],
        name="A-越界",
    )
    pb = _save_plan(
        client, exp,
        [
            {"name": "越界B", "start_temp_c": 0, "end_temp_c": 100},
            {"name": "尾段", "start_temp_c": 300, "end_temp_c": 500},
        ],
        name="B-越界",
    )
    cmp = _compare(client, pa, pb)
    codes_a = {i["code"] for i in cmp["issues"]["a"]}
    codes_b = {i["code"] for i in cmp["issues"]["b"]}
    # 两份方案各自的越界提示都保留（并排返回，互不覆盖）
    assert "out_of_range" in codes_a
    assert "out_of_range" in codes_b
    # 越界馏分仍按实测范围内部分给出产率（截断而非外推）
    fr = {f["name"]: f for f in cmp["fractions"]}
    assert fr["越界A"]["a"]["volume_yield_pct"] is not None
    assert "out_of_range" in fr["越界A"]["a"]["flags"]
    assert fr["越界B"]["b"]["volume_yield_pct"] is not None
    # 两侧都存在的馏分名不同 => 各自单列，不做减法
    assert fr["越界A"]["in_a"] and not fr["越界A"]["in_b"]
    assert fr["越界A"]["delta_volume_pct"] is None
    assert fr["越界B"]["in_b"] and not fr["越界B"]["in_a"]


def test_basis_mismatch_warns_and_never_mixes_bases(client):
    exp = _mk_experiment(client)
    pa = _save_plan(client, exp, CUTS_BASE, name="体积口径", basis="volume")
    pb = _save_plan(client, exp, CUTS_BASE, name="质量口径", basis="mass")
    cmp = _compare(client, pa, pb)
    # 口径不同 => 明确提示；但对比仍按同基准列分别进行
    assert any("口径" in n for n in cmp["notes"])
    assert any("不交叉相减" in n or "同一计量基准" in n for n in cmp["notes"])
    for f in cmp["fractions"]:
        # 切点完全相同：体积对体积、质量对质量的差值都为 0
        assert f["delta_volume_pct"] == 0
        assert f["delta_mass_pct"] == 0
    # 体积%与质量%本身并不相等（密度随温度变化）——若跨基准相减会得到假差值
    fr0 = cmp["fractions"][0]
    assert fr0["a"]["volume_yield_pct"] != fr0["a"]["mass_yield_pct"]


def test_unmatched_fractions_listed_without_subtraction(client):
    exp = _mk_experiment(client)
    pa = _save_plan(
        client, exp,
        [
            {"name": "甲", "start_temp_c": 30, "end_temp_c": 150},
            {"name": "乙", "start_temp_c": 150, "end_temp_c": 400},
        ],
        name="含乙",
    )
    pb = _save_plan(
        client, exp,
        [
            {"name": "甲", "start_temp_c": 30, "end_temp_c": 150},
            {"name": "丙", "start_temp_c": 150, "end_temp_c": 400},
        ],
        name="含丙",
    )
    cmp = _compare(client, pa, pb)
    fr = {f["name"]: f for f in cmp["fractions"]}
    assert fr["甲"]["in_a"] and fr["甲"]["in_b"] and fr["甲"]["delta_volume_pct"] == 0
    assert fr["乙"]["in_a"] and not fr["乙"]["in_b"]
    assert fr["乙"]["delta_volume_pct"] is None and fr["乙"]["delta_mass_pct"] is None
    assert fr["丙"]["in_b"] and not fr["丙"]["in_a"]
    assert fr["丙"]["change_desc"] == "仅方案B有此馏分"
    assert set(cmp["changed_fraction_names"]) == {"乙", "丙"}


def test_compare_export_markdown_and_json(client):
    exp = _mk_experiment(client)
    pa = _save_plan(client, exp, CUTS_BASE, name="基准方案")
    pb = _save_plan(client, exp, CUTS_ONE_MOVED, name="调整方案", loss=2.0)

    md = client.get(f"/api/compare/export?plan_a={pa}&plan_b={pb}&format=markdown")
    assert md.status_code == 200
    assert "方案对比" in md.text
    assert "基准方案" in md.text and "调整方案" in md.text
    assert "Δ" in md.text and "不外推" in md.text
    assert "受影响馏分" in md.text and "中" in md.text
    assert "数据提示" in md.text

    js = client.get(f"/api/compare/export?plan_a={pa}&plan_b={pb}&format=json")
    assert js.status_code == 200
    payload = js.json()
    assert "同一计量基准" in payload["scope_notice"]
    cmp = payload["comparison"]
    assert cmp["plan_a"]["name"] == "基准方案"
    assert cmp["changed_fraction_names"] == ["中"]
    assert cmp["totals"]["volume"]


def test_single_plan_endpoints_unaffected_by_compare(client):
    # 原有单方案查看与导出保持可用
    exp = _mk_experiment(client)
    pid = _save_plan(client, exp, CUTS_BASE, name="单方案", loss=1.0)
    got = client.get(f"/api/plans/{pid}")
    assert got.status_code == 200 and got.json()["result"]["cuts"]
    md = client.get(f"/api/plans/{pid}/export?format=markdown")
    assert md.status_code == 200 and "PCHIP" in md.text
    js = client.get(f"/api/plans/{pid}/export?format=json")
    assert js.status_code == 200 and js.json()["result"]["totals"]
