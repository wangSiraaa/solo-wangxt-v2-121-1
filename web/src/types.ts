export interface CurvePoint {
  temp_c: number;
  recovered_pct: number;
}

export interface DensityRow {
  temp_c: number;
  density_g_cm3: number;
}

export interface Experiment {
  id: number;
  name: string;
  sample_id?: string | null;
  feed_density_g_cm3: number;
  residue_density_g_cm3?: number | null;
  conditions: Record<string, unknown>;
  points: CurvePoint[];
  density_rows: DensityRow[];
  notes?: string | null;
  plans?: SavedPlanSummary[];
}

export interface SavedPlanSummary {
  id: number;
  name: string;
  basis: "volume" | "mass";
  loss_pct: number;
  cuts: CutInput[];
}

export interface CutInput {
  name: string;
  start_temp_c: number;
  end_temp_c: number;
}

export interface PlanInput {
  name: string;
  basis: "volume" | "mass";
  loss_pct: number;
  cuts: CutInput[];
}

export interface Issue {
  code: string;
  severity: "error" | "warning" | "info";
  message: string;
}

export interface CutResult extends CutInput {
  index: number;
  flags: string[];
  start_recovery_pct: number | null;
  end_recovery_pct: number | null;
  clipped_range_c: [number, number] | null;
  volume_yield_pct: number | null;
  mass_yield_pct: number | null;
}

export interface Overlap {
  cut_a: number;
  cut_b: number;
  cut_a_name: string;
  cut_b_name: string;
  from_temp_c: number;
  to_temp_c: number;
  width_c: number;
  volume_pct: number | null;
  mass_pct?: number | null;
  partial_outside_range: boolean;
  fully_outside_range: boolean;
}

export interface Gap {
  kind: "front" | "inter" | "tail";
  from_temp_c: number;
  to_temp_c: number;
  width_c: number;
  after_cut: string | null;
  before_cut: string | null;
  volume_pct: number | null;
  mass_pct?: number | null;
  partial_outside_range: boolean;
  fully_outside_range: boolean;
}

export interface MassTotals {
  nominal_yield_pct: number;
  union_yield_pct: number;
  overlap_pct: number;
  front_gap_pct: number;
  inter_gap_pct: number;
  tail_gap_pct: number;
  uncut_distillate_pct: number | null;
  light_unassigned_pct: number | null;
  residue_bottoms_pct: number | null;
  residue_bottoms_gross_pct: number | null;
  residual_total_pct: number | null;
  loss_pct: number;
  identity_sum_pct: number | null;
  identity_ok: boolean;
  identity_note: string;
  residue_density_g_cm3: number | null;
}

export interface Totals {
  nominal_yield_pct: number;
  union_yield_pct: number;
  overlap_pct: number;
  front_gap_pct: number;
  inter_gap_pct: number;
  tail_gap_pct: number;
  uncut_distillate_pct: number;
  light_unassigned_pct: number;
  residue_bottoms_pct: number;
  residue_bottoms_gross_pct: number;
  residual_total_pct: number;
  loss_pct: number;
  identity_sum_pct: number;
  identity_residual_pct: number;
  identity_ok: boolean;
  mass: MassTotals | null;
}

export interface EvalResult {
  basis: string;
  applicable_range: {
    temp_c: [number, number];
    recovered_pct: [number, number];
    extrapolation: string;
  };
  cuts: CutResult[];
  overlaps: Overlap[];
  gaps: Gap[];
  totals: Totals;
  issues: Issue[];
  has_blocking_errors: boolean;
  method: Record<string, string>;
}

export interface CurveSample {
  temps_c: number[];
  recovered_pct: number[];
  raw_points: CurvePoint[];
  range: { temp_c: [number, number]; recovered_pct: [number, number] };
  issues: Issue[];
  has_blocking_errors: boolean;
}

// ---- 两方案对比（同一试验）----
export interface ComparisonCutRow {
  pair_id: string;
  name: string;
  pair_status: "matched" | "only_a" | "only_b";
  a_index: number | null;
  b_index: number | null;
  a: CutResultLite | null;
  b: CutResultLite | null;
  start_temp_delta_c: number | null;
  end_temp_delta_c: number | null;
  endpoints_changed: boolean;
  volume_yield_a_pct: number | null;
  volume_yield_b_pct: number | null;
  volume_yield_delta_pct: number | null;
  mass_yield_a_pct: number | null;
  mass_yield_b_pct: number | null;
  mass_yield_delta_pct: number | null;
  affected: boolean;
  affected_reason: string;
}

export interface CutResultLite {
  index: number;
  name: string;
  start_temp_c: number;
  end_temp_c: number;
  flags: string[];
  volume_yield_pct: number | null;
  mass_yield_pct: number | null;
}

export interface ComparisonTotalRow {
  key: string;
  label: string;
  is_input: boolean;
  a_pct: number | null;
  b_pct: number | null;
  delta_b_minus_a_pct: number | null;
}

export interface ComparisonPlanHeader {
  id: number;
  name: string;
  basis: "volume" | "mass";
  loss_pct: number;
  cuts: CutInput[];
  snapshot_recomputed: boolean;
  has_blocking_errors: boolean;
}

export interface PlanComparison {
  comparison_rule: {
    same_experiment_only: boolean;
    delta_convention: string;
    no_cross_basis_subtraction: boolean;
    source: string;
  };
  experiment: { id: number; name: string; sample_id?: string | null };
  plans: { a: ComparisonPlanHeader; b: ComparisonPlanHeader };
  basis_mismatch: boolean;
  applicable_range: EvalResult["applicable_range"];
  cuts: ComparisonCutRow[];
  mass_cut_deltas_available: boolean;
  totals: {
    volume: ComparisonTotalRow[];
    mass: ComparisonTotalRow[];
    mass_meta: { available: boolean; note: string | null } | null;
  };
  overlaps: { a: Overlap[]; b: Overlap[] };
  gaps: { a: Gap[]; b: Gap[] };
  issues: {
    a: Issue[];
    b: Issue[];
    a_counts: Record<"error" | "warning" | "info", number>;
    b_counts: Record<"error" | "warning" | "info", number>;
    a_has_blocking_errors: boolean;
    b_has_blocking_errors: boolean;
  };
  affected_cut_names: string[];
  summary: {
    cuts_a: number; cuts_b: number;
    overlaps_a: number; overlaps_b: number;
    gaps_a: number; gaps_b: number;
  };
  notes: string[];
}
