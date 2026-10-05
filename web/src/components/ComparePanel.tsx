import type { Gap, Issue, Overlap, PlanComparison } from "../types";
import { cutFlagHint } from "./CutEditor";
import { g } from "../format";

function nf(v: number | null | undefined, d = 2) {
  return v === null || v === undefined || Number.isNaN(v) ? "—" : v.toFixed(d);
}

/** 带正负号的差值；0 与缺数区分显示。 */
function df(v: number | null | undefined, d = 2) {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  if (Math.abs(v) < 0.5e-3) return <span className="zero">0.00</span>;
  return <span className={v > 0 ? "pos" : "neg"}>{v > 0 ? "+" : ""}{v.toFixed(d)}</span>;
}

const KIND = { front: "前缺口", inter: "中间缺口", tail: "尾缺口" } as const;

function IssueCol({ title, issues, counts, blocking }: {
  title: string;
  issues: Issue[];
  counts: Record<"error" | "warning" | "info", number>;
  blocking: boolean;
}) {
  const order = { error: 0, warning: 1, info: 2 };
  const sorted = [...issues].sort((a, b) => order[a.severity] - order[b.severity]);
  return (
    <div className="cmp-issue-col">
      <h4>
        {title}
        <span className="cmp-counts">
          错误 {counts.error} · 需核实 {counts.warning} · 提示 {counts.info}
          {blocking && <b className="blocking">（含硬错误）</b>}
        </span>
      </h4>
      {sorted.length === 0 ? (
        <p className="ok-line">✅ 无提示</p>
      ) : (
        <ul className="cmp-issues">
          {sorted.map((it, i) => (
            <li key={i} className={`sev-${it.severity}`}>
              <span className="tag">{it.code}</span> {it.message}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function OverlapList({ items }: { items: Overlap[] }) {
  if (!items.length) return <p className="ok-line">无重叠。</p>;
  return (
    <ul className="cmp-rel">
      {items.map((o, i) => (
        <li key={i} className={o.fully_outside_range ? "muted" : "bad"}>
          {o.cut_a_name} × {o.cut_b_name}：{g(o.from_temp_c)}~{g(o.to_temp_c)} ℃
          （宽 {nf(o.width_c, 1)} ℃，体积 {nf(o.volume_pct)}%，质量 {nf(o.mass_pct)}%）
          {o.fully_outside_range ? "·范围外（不计）" : o.partial_outside_range ? "·部分越界" : ""}
        </li>
      ))}
    </ul>
  );
}

function GapList({ items }: { items: Gap[] }) {
  const real = items.filter((gp) => gp.width_c > 0);
  if (!real.length) return <p className="ok-line">无缺口。</p>;
  return (
    <ul className="cmp-rel">
      {real.map((gp, i) => (
        <li key={i} className={gp.fully_outside_range ? "muted" : "warn"}>
          {KIND[gp.kind]}
          {[gp.after_cut, gp.before_cut].filter(Boolean).length > 0
            ? `（${[gp.after_cut, gp.before_cut].filter(Boolean).join(" → ")}）` : ""}
          ：{g(gp.from_temp_c)}~{g(gp.to_temp_c)} ℃
          （宽 {nf(gp.width_c, 1)} ℃，体积 {nf(gp.volume_pct)}%，质量 {nf(gp.mass_pct)}%）
          {gp.fully_outside_range ? "·范围外（无数据）" : gp.partial_outside_range ? "·部分越界" : ""}
        </li>
      ))}
    </ul>
  );
}

function TotalTable({ rows }: { rows: PlanComparison["totals"]["volume"] }) {
  return (
    <table className="cmp-total-table">
      <thead>
        <tr><th>项目</th><th>方案A</th><th>方案B</th><th>Δ（B−A）</th></tr>
      </thead>
      <tbody>
        {rows.map((r) => (
          <tr key={r.key} className={r.is_input ? "input-row" : ""}>
            <td>{r.is_input && <span className="input-tag">输入项</span>}{r.label}</td>
            <td>{nf(r.a_pct, 3)}</td>
            <td>{nf(r.b_pct, 3)}</td>
            <td className="delta">{df(r.delta_b_minus_a_pct, 3)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

export default function ComparePanel({ cmp }: { cmp: PlanComparison }) {
  const pa = cmp.plans.a;
  const pb = cmp.plans.b;

  return (
    <div className="compare">
      <div className="cmp-rule">
        <b>对比口径：</b>同一次离线试验「{cmp.experiment.name}」的两份已保存方案；
        差值一律为<b>方案B − 方案A</b>；体积产率只与体积%相减、质量产率只与质量%相减，
        <b>不跨试验、不跨计量基准相减</b>；切点越界部分无数据、不外推，双方提示各自保留。
        {cmp.basis_mismatch && (
          <div className="cmp-warn">
            ⚠️ 两方案保存口径不同（A：{pa.basis === "mass" ? "质量%" : "体积%"}；
            B：{pb.basis === "mass" ? "质量%" : "体积%"}）。下表 Δ 列仍按各自同基准快照相减，
            请勿将一方体积%与另一方质量%直接比较。
          </div>
        )}
        {(pa.snapshot_recomputed || pb.snapshot_recomputed) && (
          <div className="cmp-info">
            {pa.snapshot_recomputed && `方案A「${pa.name}」无保存快照，A 侧数字按其保存切点重算；`}
            {pb.snapshot_recomputed && `方案B「${pb.name}」无保存快照，B 侧数字按其保存切点重算。`}
          </div>
        )}
      </div>

      <section>
        <h3>逐馏分：切点、体积/质量产率差值（★ = 受影响馏分）</h3>
        <div className="cmp-table-wrap">
          <table className="cmp-cut-table">
            <thead>
              <tr>
                <th>配对</th><th>馏分</th>
                <th>A 区间 ℃</th><th>B 区间 ℃</th><th>切点变化（初/终）℃</th>
                <th>A 体积%</th><th>B 体积%</th><th>Δ体积%</th>
                <th>A 质量%</th><th>B 质量%</th><th>Δ质量%</th>
                <th>受影响原因 / 标记</th>
              </tr>
            </thead>
            <tbody>
              {cmp.cuts.map((r) => {
                const a = r.a;
                const b = r.b;
                const change = r.pair_status !== "matched"
                  ? "—"
                  : !r.endpoints_changed
                    ? "切点相同"
                    : `${r.start_temp_delta_c && Math.abs(r.start_temp_delta_c) > 1e-6
                        ? (r.start_temp_delta_c > 0 ? "+" : "") + g(r.start_temp_delta_c) : "0"}
                       / ${r.end_temp_delta_c && Math.abs(r.end_temp_delta_c) > 1e-6
                        ? (r.end_temp_delta_c > 0 ? "+" : "") + g(r.end_temp_delta_c) : "0"}`;
                const flags = (side: typeof a) => side
                  ? side.flags.map((f) => <span key={f} className={`pill ${f}`}>{cutFlagHint(f)}</span>)
                  : null;
                return (
                  <tr key={r.pair_id} className={r.affected ? "affected" : r.pair_status !== "matched" ? "unpaired" : ""}>
                    <td>{r.pair_status === "matched" ? "配对" : r.pair_status === "only_a" ? "仅A" : "仅B"}</td>
                    <td className="name">{r.affected && <span className="star" title="受影响馏分">★</span>}{r.name}</td>
                    <td>{a ? `${g(a.start_temp_c)} ~ ${g(a.end_temp_c)}` : "—"}</td>
                    <td>{b ? `${g(b.start_temp_c)} ~ ${g(b.end_temp_c)}` : "—"}</td>
                    <td className="change">{change}</td>
                    <td>{nf(r.volume_yield_a_pct)}</td>
                    <td>{nf(r.volume_yield_b_pct)}</td>
                    <td className="delta">{df(r.volume_yield_delta_pct)}</td>
                    <td>{nf(r.mass_yield_a_pct)}</td>
                    <td>{nf(r.mass_yield_b_pct)}</td>
                    <td className="delta">{df(r.mass_yield_delta_pct)}</td>
                    <td className="reason">
                      {r.affected && <div>{r.affected_reason}</div>}
                      <span className="flags">{flags(a)}{flags(b)}</span>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
        <p className="hint">
          判定依据：馏分自身切点变化，或与其他馏分的重叠/缺口相邻关系发生变化。
          质量 Δ{" "}
          {cmp.mass_cut_deltas_available
            ? "由两方案保存快照中的质量产率（同一密度换算）同基准相减。"
            : "至少一侧缺少质量基准结果，已留空（未用体积数字代替）。"}
        </p>
      </section>

      <section>
        <h3>总量、缺口与未回收量差值</h3>
        <div className="cmp-totals-grid">
          <div>
            <h4 className="basis-h">体积基准（进料体积 %）</h4>
            <TotalTable rows={cmp.totals.volume} />
          </div>
          <div>
            <h4 className="basis-h">质量基准（进料质量 %）</h4>
            {cmp.totals.mass.length > 0 ? (
              <TotalTable rows={cmp.totals.mass} />
            ) : (
              <p className="ok-line">{cmp.totals.mass_meta?.note ?? "质量基准数据不完整，差值留空。"}</p>
            )}
            {cmp.totals.mass_meta?.note && cmp.totals.mass.length > 0 && (
              <p className="hint">{cmp.totals.mass_meta.note}</p>
            )}
          </div>
        </div>
      </section>

      <section>
        <h3>重叠 / 缺口并排（A {cmp.summary.overlaps_a} 处重叠 · B {cmp.summary.overlaps_b} 处）</h3>
        <div className="cmp-side-grid">
          <div>
            <h4 className="side-a">方案A「{pa.name}」</h4>
            <h5>重叠</h5><OverlapList items={cmp.overlaps.a} />
            <h5>缺口（{cmp.summary.gaps_a} 段）</h5><GapList items={cmp.gaps.a} />
          </div>
          <div>
            <h4 className="side-b">方案B「{pb.name}」</h4>
            <h5>重叠</h5><OverlapList items={cmp.overlaps.b} />
            <h5>缺口（{cmp.summary.gaps_b} 段）</h5><GapList items={cmp.gaps.b} />
          </div>
        </div>
      </section>

      <section>
        <h3>数据与切点提示（双方各自保留）</h3>
        <div className="cmp-side-grid">
          <IssueCol title={`方案A「${pa.name}」`} issues={cmp.issues.a}
            counts={cmp.issues.a_counts} blocking={cmp.issues.a_has_blocking_errors} />
          <IssueCol title={`方案B「${pb.name}」`} issues={cmp.issues.b}
            counts={cmp.issues.b_counts} blocking={cmp.issues.b_has_blocking_errors} />
        </div>
      </section>
    </div>
  );
}
