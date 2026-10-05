import { useEffect, useState } from "react";
import { api, compareExportUrl } from "../api";
import type { CurveSample, PlanComparison, SavedPlanSummary } from "../types";
import CurveChart from "./CurveChart";
import ComparePanel from "./ComparePanel";

interface Props {
  expId: number;
  plans: SavedPlanSummary[];
  sample: CurveSample;
}

export default function CompareSection({ expId, plans, sample }: Props) {
  const [aId, setAId] = useState<number | "">("");
  const [bId, setBId] = useState<number | "">("");
  const [cmp, setCmp] = useState<PlanComparison | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // 试验切换或新方案保存后，若当前选择失效则回到默认（前两份）
  useEffect(() => {
    const ids = new Set(plans.map((p) => p.id));
    if ((aId === "" || !ids.has(aId as number)) && plans.length) setAId(plans[0].id);
    if ((bId === "" || !ids.has(bId as number)) && plans.length > 1) setBId(plans[1].id);
    if ((bId === "" || !ids.has(bId as number)) && plans.length <= 1) setBId("");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [expId, plans]);

  useEffect(() => {
    if (aId === "" || bId === "" || aId === bId) {
      setCmp(null);
      return;
    }
    let cancelled = false;
    setLoading(true);
    setError(null);
    api.comparePlans(expId, aId as number, bId as number)
      .then((c) => { if (!cancelled) setCmp(c); })
      .catch((e) => { if (!cancelled) { setError(`对比失败：${e.message}`); setCmp(null); } })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [expId, aId, bId]);

  const planA = plans.find((p) => p.id === aId) ?? null;
  const planB = plans.find((p) => p.id === bId) ?? null;

  return (
    <div className="compare-section">
      <h2>两方案对比（同一试验，保存方案之间）</h2>
      <p className="hint">
        选择同一次试验下两份<b>已保存</b>的切点方案：曲线上将同时叠加 A（蓝色虚线）/ B（橙色点划线）
        两组切点；下方按保存的切点与结果快照列出各馏分体积/质量产率差值，
        以及重叠、缺口、未回收量与数据提示的并排结果。不会跨试验或跨计量基准相减。
      </p>

      <div className="cmp-selector">
        <label>
          <span className="swatch a" />方案A（基准）
          <select value={aId} onChange={(e) => setAId(e.target.value ? parseInt(e.target.value) : "")}>
            {plans.map((p) => <option key={p.id} value={p.id}>#{p.id} {p.name}（{p.basis === "mass" ? "质量%" : "体积%"}）</option>)}
          </select>
        </label>
        <label>
          <span className="swatch b" />方案B（对比，差值 = B − A）
          <select value={bId} onChange={(e) => setBId(e.target.value ? parseInt(e.target.value) : "")}>
            <option value="">— 请选择 —</option>
            {plans.map((p) => <option key={p.id} value={p.id}>#{p.id} {p.name}（{p.basis === "mass" ? "质量%" : "体积%"}）</option>)}
          </select>
        </label>
        {aId === bId && aId !== "" && <span className="cmp-error">请选择两份不同的方案。</span>}
        {loading && <span className="loading">对比计算中…</span>}
      </div>

      {error && <div className="banner error">{error}</div>}

      {cmp && planA && planB && (
        <>
          <CurveChart
            sample={sample}
            cuts={planA.cuts}
            overlaps={cmp.overlaps.a}
            cutsB={planB.cuts}
            overlapsB={cmp.overlaps.b}
            planNameA={`${planA.name}`}
            planNameB={`${planB.name}`}
          />
          <ComparePanel cmp={cmp} />
          <div className="save-bar">
            <span className="exports">
              导出对比摘要：
              <a href={compareExportUrl(planA.id, planB.id, "markdown")} target="_blank" rel="noreferrer">Markdown</a>
              <span className="sep">|</span>
              <a href={compareExportUrl(planA.id, planB.id, "json")} target="_blank" rel="noreferrer">JSON</a>
            </span>
          </div>
        </>
      )}
    </div>
  );
}
