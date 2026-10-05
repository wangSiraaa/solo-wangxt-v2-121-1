"""同试验两方案对比 API 的验收测试。"""
from __future__ import annotations


def _two_plans(client, exp_id, cuts_a, cuts_b, basis="volume", loss=0.0):
    pa = {
        "name": "方案A", "basis": basis, "loss_pct": loss,
        "cuts": [{"name": n, "start_temp_c": s, "end_temp_c": e} for n, s, e in cuts_a],
    }
    pb = {
        "name": "方案B", "basis": basis, "loss_pct": loss,
        "cuts": [{"name": n, "start_temp_c": s, "end_temp_c": e} for n, s, e in cuts_b],
    }
    ida = client.post(f"/api/experiments/{exp_id}/plans", json=pa).json()["id"]
    idb = client.post(f"/api/experiments/{exp_id}/plans", json=pb).json()["id"]
    r = client.get(f"/api/experiments/{exp_id}/plans/compare", params={"a": ida, "b": idb})
    assert r.status_code == 200, r.text
    return ida, idb, r.json()


def test_compare_single_cut_move_locates_affected_cuts(client):
    client.post("/api/seed")
    exps = client.get("/api/experiments").json()
    bid = exps[1]["id"]  # 示例B：0~100% 完整曲线

    cuts_a = [
        ("轻石脑油", 30, 100),
        ("航煤", 100, 185),
        ("柴油", 185, 320),
        ("VGO", 320, 600),
    ]
    # 只把航煤的终切点 185 -> 210（同时柴油起点跟着移到 210 保持连续）
    cuts_b = [
        ("轻石脑油", 30, 100),
        ("航煤", 100, 210),
        ("柴油", 210, 320),
        ("VGO", 320, 600),
    ]
    _, _, cmp_ = _two_plans(client, bid, cuts_a, cuts_b)

    by_name = {r["name"]: r for r in cmp_["cuts"]}
    # 受影响：航煤（自身切点变）、柴油（起点变）
    assert by_name["航煤"]["affected"] and by_name["柴油"]["affected"]
    assert "切点发生变化" in by_name["航煤"]["affected_reason"]
    # 未动的馏分不应被标记
    assert not by_name["轻石脑油"]["affected"]
    assert not by_name["VGO"]["affected"]
    # 差值方向：航煤变大、柴油变小，且二者体积变化量互为相反数
    d_kerosene = by_name["航煤"]["volume_yield_delta_pct"]
    d_diesel = by_name["柴油"]["volume_yield_delta_pct"]
    assert d_kerosene > 0 and d_diesel < 0
    assert abs(d_kerosene + d_diesel) < 0.01
    # 并集/总量在连续切割重排下不变
    totals = {r["key"]: r for r in cmp_["totals"]["volume"]}
    assert totals["union_yield_pct"]["delta_b_minus_a_pct"] == 0
    assert totals["residue_bottoms_gross_pct"]["delta_b_minus_a_pct"] == 0
    # 质量差值同为同基准内计算，且与体积差值不同
    assert by_name["航煤"]["mass_yield_delta_pct"] is not None
    assert by_name["航煤"]["mass_yield_delta_pct"] != d_kerosene


def test_compare_out_of_range_cuts_keep_each_sides_tips(client):
    exps = client.get("/api/experiments").json()
    aid = exps[0]["id"]  # 示例A：实测 55~340℃，末点 90%

    cuts_a = [("轻", 55, 185), ("重", 185, 370)]   # B方案(作为A侧)高温越界
    cuts_b = [("轻", 30, 185), ("重", 185, 340)]   # A方案(作为B侧)低温越界
    ida, idb, cmp_ = _two_plans(client, aid, cuts_a, cuts_b)

    # 两侧各自保留越界提示
    assert any(i["code"] == "out_of_range" and "370" in i["message"]
               for i in cmp_["issues"]["a"])
    assert any(i["code"] == "out_of_range" and "30" in i["message"]
               for i in cmp_["issues"]["b"])
    # 各自馏分 flags 仍在
    a_rows = {r["name"]: r for r in cmp_["cuts"]}
    assert "out_of_range" in (a_rows["重"]["a"] or {}).get("flags", [])
    assert "out_of_range" in (a_rows["轻"]["b"] or {}).get("flags", [])
    # 越界侧截断后的体积产率仍可相减（同基准）
    assert a_rows["重"]["volume_yield_a_pct"] is not None
    assert a_rows["重"]["volume_yield_b_pct"] is not None
    assert a_rows["重"]["volume_yield_delta_pct"] is not None


def test_compare_rejects_cross_experiment(client):
    exps = client.get("/api/experiments").json()
    p1 = client.post(f"/api/experiments/{exps[0]['id']}/plans", json={
        "name": "a", "basis": "volume", "loss_pct": 0,
        "cuts": [{"name": "f", "start_temp_c": 55, "end_temp_c": 185}],
    }).json()["id"]
    p2 = client.post(f"/api/experiments/{exps[1]['id']}/plans", json={
        "name": "b", "basis": "volume", "loss_pct": 0,
        "cuts": [{"name": "f", "start_temp_c": 30, "end_temp_c": 100}],
    }).json()["id"]
    # 跨试验：通过全局导出路径对比应 422
    r = client.get(f"/api/plans/compare/{p1}/{p2}/export")
    assert r.status_code == 422 and "同一次试验" in r.text
    # 在错误试验路径下对比应 422
    r = client.get(f"/api/experiments/{exps[1]['id']}/plans/compare",
                   params={"a": p1, "b": p2})
    assert r.status_code == 422
    # 同方案对比应 400
    r = client.get(f"/api/experiments/{exps[0]['id']}/plans/compare",
                   params={"a": p1, "b": p1})
    assert r.status_code == 400


def test_compare_different_basis_does_not_cross_subtract(client):
    exps = client.get("/api/experiments").json()
    bid = exps[1]["id"]
    cuts = [("轻石脑油", 30, 100), ("柴油", 185, 320)]
    pa = {"name": "体积口径", "basis": "volume", "loss_pct": 0,
          "cuts": [{"name": n, "start_temp_c": s, "end_temp_c": e} for n, s, e in cuts]}
    pb = {"name": "质量口径", "basis": "mass", "loss_pct": 0,
          "cuts": [{"name": n, "start_temp_c": s, "end_temp_c": e} for n, s, e in cuts]}
    ida = client.post(f"/api/experiments/{bid}/plans", json=pa).json()["id"]
    idb = client.post(f"/api/experiments/{bid}/plans", json=pb).json()["id"]
    cmp_ = client.get(f"/api/experiments/{bid}/plans/compare",
                      params={"a": ida, "b": idb}).json()
    assert cmp_["basis_mismatch"] is True
    # 切点完全相同 => 体积差、质量差都为 0（各自同基准快照相减），而非体积-质量混减
    row = {r["name"]: r for r in cmp_["cuts"]}["轻石脑油"]
    assert row["volume_yield_delta_pct"] == 0
    assert row["mass_yield_delta_pct"] == 0
    assert any("不跨基准" in n or "口径不同" in n for n in cmp_["notes"])


def test_compare_export_markdown_and_json(client):
    exps = client.get("/api/experiments").json()
    bid = exps[1]["id"]
    cuts_a = [("轻", 30, 100), ("重", 100, 600)]
    cuts_b = [("轻", 30, 120), ("重", 120, 600)]
    ida, idb, _ = _two_plans(client, bid, cuts_a, cuts_b)

    md = client.get(f"/api/plans/compare/{ida}/{idb}/export?format=markdown")
    assert md.status_code == 200
    text = md.text
    assert "对比摘要" in text and "方案B − 方案A" in text
    assert "不跨基准" in text and "受影响馏分" in text
    assert "切点越界" in text or "无提示" in text

    js = client.get(f"/api/plans/compare/{ida}/{idb}/export?format=json")
    assert js.status_code == 200
    body = js.json()
    assert body["comparison"]["comparison_rule"]["no_cross_basis_subtraction"] is True
    assert body["comparison"]["experiment"]["id"] == bid


def test_single_plan_view_and_export_still_works(client):
    """原有单方案查看/导出回归。"""
    exps = client.get("/api/experiments").json()
    bid = exps[1]["id"]
    saved = client.post(f"/api/experiments/{bid}/plans", json={
        "name": "单方案", "basis": "volume", "loss_pct": 0,
        "cuts": [{"name": "f", "start_temp_c": 30, "end_temp_c": 185}],
    }).json()
    pid = saved["id"]
    got = client.get(f"/api/plans/{pid}")
    assert got.status_code == 200 and got.json()["plan"]["name"] == "单方案"
    md = client.get(f"/api/plans/{pid}/export?format=markdown")
    assert md.status_code == 200 and "PCHIP" in md.text
    js = client.get(f"/api/plans/{pid}/export?format=json")
    assert js.status_code == 200 and js.json()["plan"]["id"] == pid


def test_compare_uses_saved_snapshot_not_live_edits(client):
    """对比必须基于保存切点+快照：保存后再改试验外的编辑器内容不影响对比。"""
    exps = client.get("/api/experiments").json()
    bid = exps[1]["id"]
    ida = client.post(f"/api/experiments/{bid}/plans", json={
        "name": "A", "basis": "volume", "loss_pct": 0,
        "cuts": [{"name": "f", "start_temp_c": 30, "end_temp_c": 100}],
    }).json()["id"]
    idb = client.post(f"/api/experiments/{bid}/plans", json={
        "name": "B", "basis": "volume", "loss_pct": 0,
        "cuts": [{"name": "f", "start_temp_c": 30, "end_temp_c": 185}],
    }).json()["id"]
    cmp_ = client.get(f"/api/experiments/{bid}/plans/compare",
                      params={"a": ida, "b": idb}).json()
    row = cmp_["cuts"][0]
    assert row["a"]["end_temp_c"] == 100 and row["b"]["end_temp_c"] == 185
    assert row["end_temp_delta_c"] == 85
    assert row["volume_yield_delta_pct"] > 0
    assert cmp_["plans"]["a"]["snapshot_recomputed"] is False
