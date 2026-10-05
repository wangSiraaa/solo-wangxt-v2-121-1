import type { Gap, Issue, Overlap, PlanComparison, SavedPlanSummary } from "../types";
import { compareExportUrl } from "../api";
import { cutFlagHint } from "./CutEditor";
import { g } from "../format";

const KIND = { front: "前缺口", inter: "中间缺口", tail: "尾缺口" } as const;

function fmt(v: number | null | undefined, d = 2) {
  return v === null || v === undefined || Number.isNaN(v) ? "—" : v.toFixed(d);
}

function fmtDelta(v: number | null | undefined) {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  return (v > 0 ? "+" : "") + v.toFixed(2);
}

function deltaCls(v: number | null | undefined) {
  if (v === null || v === undefined || Number.isNaN(v) || Math.abs(v) < 1e-9) return "delta";
  return "delta nonzero";
}

interface Props {
  plans: SavedPlanSummary[];
  planA: number | null;
  planB: number | null;
  comparison: PlanComparison | null;
  error: string | null;
  overlay: boolean;
  onSelectA: (id: number | null) => void;
  onSelectB: (id: number | null) => void;
  onOverlayChange: (v: boolean) => void;
}

function PlanSelect({
  label, value, plans, onChange,
}: {
  label: string;
  value: number | null;
  plans: SavedPlanSummary[];
  onChange: (id: number | null) => void;
}) {
  return (
    <label>{label}
      <select
        value={value ?? ""}
        onChange={(e) => onChange(e.target.value ? Number(e.target.value) : null)}
      >
        <option value="">请选择</option>
        {plans.map((p) => (
          <option key={p.id} value={p.id}>
            #{p.id} {p.name}（{p.basis === "mass" ? "质量" : "体积"}基准）
          </option>
        ))}
      </select>
    </label>
  );
}

function OverlapBlock({ items }: { items: Overlap[] }) {
  if (items.length === 0) return <p className="ok-line">无重叠。</p>;
  return (
    <ul className="mini-list">
      {items.map((o, i) => (
        <li key={i}>
          {o.cut_a_name} × {o.cut_b_name}：{g(o.from_temp_c)}~{g(o.to_temp_c)} ℃
          （{fmt(o.volume_pct)} 体积% / {fmt(o.mass_pct)} 质量%）
          {o.fully_outside_range ? "（范围外，不计）" : o.partial_outside_range ? "（部分越界）" : ""}
        </li>
      ))}
    </ul>
  );
}

function GapBlock({ items }: { items: Gap[] }) {
  const shown = items.filter((gp) => gp.width_c > 0);
  if (shown.length === 0) return <p className="ok-line">无缺口。</p>;
  return (
    <ul className="mini-list">
      {shown.map((gp, i) => (
        <li key={i} className={gp.fully_outside_range ? "muted" : ""}>
          {KIND[gp.kind]}：{g(gp.from_temp_c)}~{g(gp.to_temp_c)} ℃
          （{fmt(gp.volume_pct)} 体积% / {fmt(gp.mass_pct)} 质量%）
          {gp.fully_outside_range ? "（范围外，无数据）" : gp.partial_outside_range ? "（部分越界）" : ""}
        </li>
      ))}
    </ul>
  );
}

function IssueList({ items }: { items: Issue[] }) {
  if (items.length === 0) return <p className="ok-line">✅ 未发现数据与切点问题</p>;
  const order = { error: 0, warning: 1, info: 2 };
  const sorted = [...items].sort((a, b) => order[a.severity] - order[b.severity]);
  const icon = { error: "⛔", warning: "⚠️", info: "ℹ️" } as const;
  return (
    <ul className="mini-list issues-mini">
      {sorted.map((it, i) => (
        <li key={i} className={it.severity}>
          {icon[it.severity]} [{it.code}] {it.message}
        </li>
      ))}
    </ul>
  );
}

export default function ComparePanel({
  plans, planA, planB, comparison, error, overlay,
  onSelectA, onSelectB, onOverlayChange,
}: Props) {
  const ready = comparison !== null;
  return (
    <div className="compare">
      <h3>方案对比（同一试验 · 两份已保存方案 · Δ = B − A）</h3>
      {plans.length < 2 && (
        <p className="hint">
          当前试验只有 {plans.length} 份已保存方案。先在上方调整切点并「保存方案」，
          保存至少两份后即可在此选择对比。
        </p>
      )}
      <div className="row">
        <PlanSelect label="方案A（被减侧）" value={planA} plans={plans} onChange={onSelectA} />
        <PlanSelect label="方案B（对比侧）" value={planB} plans={plans} onChange={onSelectB} />
        <label className="chk">
          <input type="checkbox" checked={overlay} onChange={(e) => onOverlayChange(e.target.checked)} />
          在曲线图上同时标出两组切点
        </label>
        {ready && planA !== null && planB !== null && (
          <span className="exports">
            导出对比摘要：
            <a href={compareExportUrl(planA, planB, "markdown")} target="_blank" rel="noreferrer">Markdown</a>
            <span className="sep">|</span>
            <a href={compareExportUrl(planA, planB, "json")} target="_blank" rel="noreferrer">JSON</a>
          </span>
        )}
      </div>
      {planA !== null && planB !== null && planA === planB && (
        <p className="hint">请选择两份不同的方案。</p>
      )}
      {error && <div className="banner error">{error}</div>}

      {comparison && (
        <>
          {comparison.notes.map((n, i) => (
            <div key={i} className="cmp-note">ℹ️ {n}</div>
          ))}

          <section>
            <h4>① 馏分产率对照（差值只在同一计量基准内计算）</h4>
            <table className="yield-table">
              <thead>
                <tr>
                  <th rowSpan={2}>馏分</th>
                  <th colSpan={3}>方案A：{comparison.plan_a.name}</th>
                  <th colSpan={3}>方案B：{comparison.plan_b.name}</th>
                  <th rowSpan={2}>Δ体积%</th>
                  <th rowSpan={2}>Δ质量%</th>
                  <th rowSpan={2}>切点变化</th>
                </tr>
                <tr>
                  <th>区间 ℃</th><th>体积%</th><th>质量%</th>
                  <th>区间 ℃</th><th>体积%</th><th>质量%</th>
                </tr>
              </thead>
              <tbody>
                {comparison.fractions.map((f) => (
                  <tr key={f.name}
                    className={f.interval_changed ? "changed" : (!f.in_a || !f.in_b ? "onesided" : "")}>
                    <td>
                      {f.name}
                      {!f.in_a && <span className="pill">仅B</span>}
                      {!f.in_b && <span className="pill">仅A</span>}
                      <span className="flags">
                        {(f.a?.flags ?? f.b?.flags ?? []).map((fl) => (
                          <span key={fl} className={`pill ${fl}`}>{cutFlagHint(fl)}</span>
                        ))}
                      </span>
                    </td>
                    <td>{f.a ? `${g(f.a.start_temp_c)} ~ ${g(f.a.end_temp_c)}` : "—"}</td>
                    <td>{fmt(f.a?.volume_yield_pct)}</td>
                    <td>{fmt(f.a?.mass_yield_pct)}</td>
                    <td>{f.b ? `${g(f.b.start_temp_c)} ~ ${g(f.b.end_temp_c)}` : "—"}</td>
                    <td>{fmt(f.b?.volume_yield_pct)}</td>
                    <td>{fmt(f.b?.mass_yield_pct)}</td>
                    <td className={deltaCls(f.delta_volume_pct)}>{fmtDelta(f.delta_volume_pct)}</td>
                    <td className={deltaCls(f.delta_mass_pct)}>{fmtDelta(f.delta_mass_pct)}</td>
                    <td className="change-desc">{f.change_desc}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <p className="affected">
              受影响馏分：
              {comparison.changed_fraction_names.length
                ? <b>{comparison.changed_fraction_names.join("、")}</b>
                : "无（两方案切点与产率一致）"}
            </p>
          </section>

          <section>
            <h4>② 总量与未回收量对照</h4>
            <div className="compare-cols">
              <div>
                <h5>体积基准（进料体积 %）</h5>
                <table>
                  <thead><tr><th>项目</th><th>A</th><th>B</th><th>Δ</th></tr></thead>
                  <tbody>
                    {comparison.totals.volume.map((r) => (
                      <tr key={r.key}>
                        <td>{r.label}</td>
                        <td>{fmt(r.a)}</td>
                        <td>{fmt(r.b)}</td>
                        <td className={deltaCls(r.delta)}>{fmtDelta(r.delta)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                <p className="hint">
                  体积闭合：A {comparison.totals.identity_ok.a ? "✅" : "❌"}
                  {" / "}B {comparison.totals.identity_ok.b ? "✅" : "❌"}
                </p>
              </div>
              {comparison.totals.mass && (
                <div>
                  <h5>质量基准（进料质量 %）</h5>
                  <table>
                    <thead><tr><th>项目</th><th>A</th><th>B</th><th>Δ</th></tr></thead>
                    <tbody>
                      {comparison.totals.mass.map((r) => (
                        <tr key={r.key}>
                          <td>{r.label}</td>
                          <td>{fmt(r.a)}</td>
                          <td>{fmt(r.b)}</td>
                          <td className={deltaCls(r.delta)}>{fmtDelta(r.delta)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                  {(["a", "b"] as const).map((tag) => {
                    const mi = comparison.totals.mass_identity?.[tag];
                    return mi?.note ? (
                      <p key={tag} className="hint">质量说明（{tag.toUpperCase()}）：{mi.note}</p>
                    ) : null;
                  })}
                </div>
              )}
            </div>
          </section>

          <section>
            <h4>③ 重叠与缺口（并排）</h4>
            <div className="compare-cols">
              {(["a", "b"] as const).map((tag) => (
                <div key={tag} className="compare-col">
                  <h5>方案{tag.toUpperCase()}：{tag === "a" ? comparison.plan_a.name : comparison.plan_b.name}</h5>
                  <OverlapBlock items={comparison.overlaps[tag]} />
                  <GapBlock items={comparison.gaps[tag]} />
                </div>
              ))}
            </div>
          </section>

          <section>
            <h4>④ 数据提示（并排，各自核实）</h4>
            <div className="compare-cols">
              {(["a", "b"] as const).map((tag) => (
                <div key={tag} className="compare-col">
                  <h5>方案{tag.toUpperCase()}：{tag === "a" ? comparison.plan_a.name : comparison.plan_b.name}</h5>
                  <IssueList items={comparison.issues[tag]} />
                </div>
              ))}
            </div>
          </section>
        </>
      )}
    </div>
  );
}
