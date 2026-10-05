"""FastAPI 入口。

端点
----
GET  /api/health
POST /api/seed                 导入 data/seed.json（仅库空时或 force=true）
GET  /api/experiments
POST /api/experiments
GET  /api/experiments/{id}
GET  /api/experiments/{id}/curve/sample
POST /api/experiments/{id}/evaluate                 仅计算，不落库
POST /api/experiments/{id}/plans                    保存方案
GET  /api/plans/{id}                                读方案（重新计算）
GET  /api/plans/{id}/export?format=markdown|json    导出
GET  /api/experiments/{id}/plans/compare?a=&b=      同试验两份已保存方案对比
GET  /api/plans/compare/{a_id}/{b_id}/export        对比摘要导出（markdown|json）

仅处理库中给定的离线试验数据，不连接任何现场装置。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse, Response
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from .config import settings
from .comparison import build_comparison
from .curve import prepare_curve
from .database import get_session, init_db
from .density import prepare_density
from .exporters import (
    build_comparison_markdown,
    build_markdown,
    comparison_to_json,
    to_json,
)
from .models import Experiment, Plan
from .planning import evaluate_plan
from .schemas import ExperimentIn, ExperimentOut, PlanIn, PlanOut

app = FastAPI(
    title="蒸馏曲线切点与产率核对（培训）",
    version="1.0.0",
    description="离线蒸馏试验数据的单调插值（PCHIP）、馏分切割与质量/体积产率核对。",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_methods=["*"],
    allow_headers=["*"],
)

SEED_PATH = Path(__file__).resolve().parents[2] / "data" / "seed.json"


@app.on_event("startup")
async def _startup() -> None:
    await init_db()


@app.get("/api/health")
async def health() -> dict:
    return {"status": "ok"}


# ---- 公共计算辅助 ----
def _eval_experiment(exp: Experiment, payload: PlanIn) -> dict:
    curve = prepare_curve(exp.points)
    density = prepare_density(exp.density_rows or [])
    return evaluate_plan(
        curve=curve,
        cuts=[c.model_dump() for c in payload.cuts],
        loss_pct=payload.loss_pct,
        basis=payload.basis,
        density=density,
        feed_density=exp.feed_density_g_cm3,
        residue_density=exp.residue_density_g_cm3,
    )


def _exp_to_out(exp: Experiment) -> dict:
    return {
        "id": exp.id,
        "name": exp.name,
        "sample_id": exp.sample_id,
        "feed_density_g_cm3": exp.feed_density_g_cm3,
        "residue_density_g_cm3": exp.residue_density_g_cm3,
        "conditions": exp.conditions or {},
        "points": exp.points or [],
        "density_rows": exp.density_rows or [],
        "notes": exp.notes,
    }


# ---- 种子 ----
@app.post("/api/seed")
async def load_seed(force: bool = False) -> dict:
    async for session in get_session():
        if not force:
            n = (await session.execute(select(func.count(Experiment.id)))).scalar_one()
            if n:
                raise HTTPException(409, f"库中已有 {n} 条试验；确认覆盖请用 force=true")
        if force:
            for p in (await session.execute(select(Plan))).scalars().all():
                await session.delete(p)
            for e in (await session.execute(select(Experiment))).scalars().all():
                await session.delete(e)
            await session.flush()

        data = json.loads(SEED_PATH.read_text(encoding="utf-8"))
        created = 0
        for item in data["experiments"]:
            plans = item.pop("plans", [])
            residue_density = item.pop("residue_density_g_cm3", None)
            exp = Experiment(
                name=item["name"],
                sample_id=item.get("sample_id"),
                feed_density_g_cm3=item["feed_density_g_cm3"],
                residue_density_g_cm3=residue_density,
                conditions=item.get("conditions") or {},
                points=item["points"],
                density_rows=item.get("density_rows", []),
                notes=item.get("notes"),
            )
            session.add(exp)
            await session.flush()
            for p in plans:
                payload = PlanIn(**p)
                result = _eval_experiment(exp, payload)
                session.add(
                    Plan(
                        experiment_id=exp.id,
                        name=payload.name,
                        basis=payload.basis,
                        cuts=[c.model_dump() for c in payload.cuts],
                        loss_pct=payload.loss_pct,
                        result_snapshot=result,
                    )
                )
            created += 1
        await session.commit()
        return {"loaded_experiments": created}


# ---- 试验 ----
@app.get("/api/experiments")
async def list_experiments() -> list[ExperimentOut]:
    async for session in get_session():
        rows = (await session.execute(select(Experiment).order_by(Experiment.id))).scalars()
        return [ExperimentOut.model_validate(r) for r in rows]


@app.post("/api/experiments", status_code=201)
async def create_experiment(payload: ExperimentIn) -> ExperimentOut:
    async for session in get_session():
        exp = Experiment(
            name=payload.name,
            sample_id=payload.sample_id,
            feed_density_g_cm3=payload.feed_density_g_cm3,
            residue_density_g_cm3=payload.residue_density_g_cm3,
            conditions=payload.conditions,
            points=[p.model_dump() for p in payload.points],
            density_rows=[d.model_dump() for d in payload.density_rows],
            notes=payload.notes,
        )
        curve = prepare_curve(exp.points)  # 提前暴露硬错误
        if curve.hard_errors:
            raise HTTPException(
                422,
                detail={
                    "message": "蒸馏曲线数据校验未通过，请先核实修正",
                    "issues": [i.as_dict() for i in curve.hard_errors],
                },
            )
        session.add(exp)
        await session.commit()
        await session.refresh(exp)
        return ExperimentOut.model_validate(exp)


@app.get("/api/experiments/{exp_id}")
async def get_experiment(exp_id: int) -> dict:
    async for session in get_session():
        exp = await session.scalar(
            select(Experiment)
            .where(Experiment.id == exp_id)
            .options(selectinload(Experiment.plans))
        )
        if exp is None:
            raise HTTPException(404, "试验不存在")
        out = _exp_to_out(exp)
        out["plans"] = [
            {
                "id": p.id,
                "name": p.name,
                "basis": p.basis,
                "loss_pct": p.loss_pct,
                "cuts": p.cuts,
            }
            for p in sorted(exp.plans, key=lambda x: x.id)
        ]
        return out


@app.get("/api/experiments/{exp_id}/curve/sample")
async def curve_sample(exp_id: int, n: int = Query(200, ge=10, le=1000)) -> dict:
    async for session in get_session():
        exp = await session.get(Experiment, exp_id)
        if exp is None:
            raise HTTPException(404, "试验不存在")
        curve = prepare_curve(exp.points)
        ts, rs = curve.sample(n)
        return {
            "temps_c": ts,
            "recovered_pct": rs,
            "raw_points": exp.points,
            "range": {"temp_c": [curve.t_min, curve.t_max],
                      "recovered_pct": [curve.r_min, curve.r_max]},
            "issues": [i.as_dict() for i in curve.issues],
            "has_blocking_errors": bool(curve.hard_errors),
        }


# ---- 方案计算 / 保存 ----
def _plan_header_dict(plan: Plan) -> dict:
    return {
        "id": plan.id,
        "experiment_id": plan.experiment_id,
        "name": plan.name,
        "basis": plan.basis,
        "cuts": plan.cuts,
        "loss_pct": plan.loss_pct,
    }


def _resolve_snapshot(exp: Experiment, plan: Plan) -> tuple[dict, bool]:
    """返回（用于对比的结果，是否为重算）。

    优先使用保存时刻的结果快照；快照缺失（旧数据）时按保存切点重算并标记。
    """
    if isinstance(plan.result_snapshot, dict) and plan.result_snapshot.get("cuts"):
        return plan.result_snapshot, False
    payload = PlanIn(
        name=plan.name, basis=plan.basis, cuts=plan.cuts, loss_pct=plan.loss_pct
    )
    return _eval_experiment(exp, payload), True


async def _load_compare_pair(
    session, plan_a_id: int, plan_b_id: int
) -> tuple[Experiment, Plan, dict, bool, Plan, dict, bool]:
    if plan_a_id == plan_b_id:
        raise HTTPException(400, "请选择两份不同的方案进行对比")
    plans: dict[int, Plan] = {}
    for pid in (plan_a_id, plan_b_id):
        p = await session.scalar(
            select(Plan).where(Plan.id == pid).options(selectinload(Plan.experiment))
        )
        if p is None:
            raise HTTPException(404, f"方案 #{pid} 不存在")
        plans[pid] = p
    pa, pb = plans[plan_a_id], plans[plan_b_id]
    if pa.experiment_id != pb.experiment_id:
        raise HTTPException(
            422,
            "两份方案不属于同一次试验：曲线/密度/进料基准不同，"
            "产率数字不能直接相减，请在同一试验下选择方案",
        )
    exp = pa.experiment
    snap_a, rec_a = _resolve_snapshot(exp, pa)
    snap_b, rec_b = _resolve_snapshot(exp, pb)
    return exp, pa, snap_a, rec_a, pb, snap_b, rec_b


@app.post("/api/experiments/{exp_id}/evaluate")
async def evaluate(exp_id: int, payload: PlanIn) -> dict:
    async for session in get_session():
        exp = await session.get(Experiment, exp_id)
        if exp is None:
            raise HTTPException(404, "试验不存在")
        return _eval_experiment(exp, payload)


@app.post("/api/experiments/{exp_id}/plans", status_code=201)
async def create_plan(exp_id: int, payload: PlanIn) -> dict:
    async for session in get_session():
        exp = await session.get(Experiment, exp_id)
        if exp is None:
            raise HTTPException(404, "试验不存在")
        result = _eval_experiment(exp, payload)
        plan = Plan(
            experiment_id=exp_id,
            name=payload.name,
            basis=payload.basis,
            cuts=[c.model_dump() for c in payload.cuts],
            loss_pct=payload.loss_pct,
            result_snapshot=result,
        )
        session.add(plan)
        await session.commit()
        await session.refresh(plan)
        return {"id": plan.id, "result": result}


@app.get("/api/plans/{plan_id}")
async def get_plan(plan_id: int) -> dict:
    async for session in get_session():
        plan = await session.scalar(
            select(Plan)
            .where(Plan.id == plan_id)
            .options(selectinload(Plan.experiment))
        )
        if plan is None:
            raise HTTPException(404, "方案不存在")
        payload = PlanIn(
            name=plan.name, basis=plan.basis, cuts=plan.cuts, loss_pct=plan.loss_pct
        )
        result = _eval_experiment(plan.experiment, payload)
        return {
            "plan": PlanOut.model_validate(plan).model_dump(),
            "result": result,
        }


@app.get("/api/plans/{plan_id}/export")
async def export_plan(
    plan_id: int, format: Literal["markdown", "json"] = "markdown"
) -> Response:
    async for session in get_session():
        plan = await session.scalar(
            select(Plan)
            .where(Plan.id == plan_id)
            .options(selectinload(Plan.experiment))
        )
        if plan is None:
            raise HTTPException(404, "方案不存在")
        payload = PlanIn(
            name=plan.name, basis=plan.basis, cuts=plan.cuts, loss_pct=plan.loss_pct
        )
        exp = plan.experiment
        result = _eval_experiment(exp, payload)
        exp_out = _exp_to_out(exp)
        plan_out = {
            "id": plan.id,
            "name": plan.name,
            "basis": plan.basis,
            "cuts": plan.cuts,
            "loss_pct": plan.loss_pct,
        }
        if format == "json":
            return Response(
                to_json(exp_out, plan_out, result),
                media_type="application/json",
                headers={
                    "Content-Disposition": 'attachment; filename="distillation_plan.json"'
                },
            )
        md = build_markdown(exp_out, plan_out, result)
        return PlainTextResponse(
            md,
            media_type="text/markdown; charset=utf-8",
            headers={
                "Content-Disposition": 'attachment; filename="distillation_plan.md"'
            },
        )


# ---- 两方案对比（同一试验）----
@app.get("/api/experiments/{exp_id}/plans/compare")
async def compare_plans(
    exp_id: int, a: int = Query(..., description="方案A（基准方案）ID"),
    b: int = Query(..., description="方案B（对比方案）ID"),
) -> dict:
    async for session in get_session():
        exp = await session.get(Experiment, exp_id)
        if exp is None:
            raise HTTPException(404, "试验不存在")
        _owner_exp, pa, snap_a, rec_a, pb, snap_b, rec_b = await _load_compare_pair(
            session, a, b
        )
        if pa.experiment_id != exp_id or pb.experiment_id != exp_id:
            raise HTTPException(422, "所选方案不属于该试验，不能在本试验下对比")
        return build_comparison(
            experiment=_exp_to_out(exp),
            plan_a=_plan_header_dict(pa),
            snapshot_a=snap_a,
            plan_b=_plan_header_dict(pb),
            snapshot_b=snap_b,
            snapshot_a_recomputed=rec_a,
            snapshot_b_recomputed=rec_b,
        )


@app.get("/api/plans/compare/{plan_a_id}/{plan_b_id}/export")
async def export_comparison(
    plan_a_id: int,
    plan_b_id: int,
    format: Literal["markdown", "json"] = "markdown",
) -> Response:
    async for session in get_session():
        exp, pa, snap_a, rec_a, pb, snap_b, rec_b = await _load_compare_pair(
            session, plan_a_id, plan_b_id
        )
        exp_out = _exp_to_out(exp)
        comparison = build_comparison(
            experiment=exp_out,
            plan_a=_plan_header_dict(pa),
            snapshot_a=snap_a,
            plan_b=_plan_header_dict(pb),
            snapshot_b=snap_b,
            snapshot_a_recomputed=rec_a,
            snapshot_b_recomputed=rec_b,
        )
        if format == "json":
            return Response(
                comparison_to_json(exp_out, comparison),
                media_type="application/json",
                headers={
                    "Content-Disposition":
                        'attachment; filename="plan_comparison.json"'
                },
            )
        md = build_comparison_markdown(exp_out, comparison)
        return PlainTextResponse(
            md,
            media_type="text/markdown; charset=utf-8",
            headers={
                "Content-Disposition":
                    'attachment; filename="plan_comparison.md"'
            },
        )
