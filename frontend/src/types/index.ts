export type RouteName = 'dashboard' | 'replay' | 'episodes' | 'missions' | 'analytics' | 'runner';

export interface TickData {
  t: number;
  x: number;
  y: number;
  th: number;
  v: number;
  w: number;
  cv: number;
  cw: number;
  st: 'moving' | 'arrived' | 'waiting' | 'lost' | 'estop';
  pe: [number, number, number] | null;
  nt: string | null;
  m: string | null;
  drv: 1 | 0;
  fbd: 1 | 0;
  vmax: number | null;
  hum: number | null;
  obj: number | null;
  coll: 1 | 0;
  cont: 1 | 0;
  peds?: [number, number][];
  lidarRays?: { angle: number; dist: number }[];
}

export interface EpisodeData {
  id: string;
  severity: 'warning' | 'info' | 'critical' | 'success';
  type: string;
  category: string;
  t_start: number;
  t_end: number;
  x: number;
  y: number;
  cost: number;
  ruleExplanation?: string;
  telemetrySnapshot?: {
    v: number;
    cv: number;
    hum: number | null;
    obj: number | null;
    pe_error: number;
    status: string;
    note: string;
  };
}

export interface MissionData {
  id: string;
  from: string;
  to: string;
  fromLabel: string;
  toLabel: string;
  status: 'DELIVERED' | 'TIMEOUT' | 'FAILED';
  t_start: number;
  t_end: number;
  t_arrival: number;
  hold_duration_s: number;
  hold_ticks: number;
  max_hold_dist: number;
  tol: number;
  deadline_s: number;
  safety_margin_s: number;
  reference_length_m: number;
  actual_time_s: number;
}

export interface ScoreBlock {
  key: string;
  name: string;
  achieved: number;
  max: number;
  percentage: number;
}

export interface ReportData {
  scenario: string;
  seed: number;
  totalScore: number;
  counted: boolean;
  blocks: ScoreBlock[];
  computeBudget: {
    limit_s: number;
    fact_s: number;
    mean_step_ms: number;
    max_step_ms: number;
    step_distribution: { bin: number; count: number }[];
  };
  sandbox: {
    violations: string[];
    stderr_tail: string[];
  };
}

export interface MapData {
  bounds: [number, number, number, number];
  drivable: { id: string; points: [number, number][] }[];
  buildings: { id: string; points: [number, number][] }[];
  zones: { id: string; type: string; points: [number, number][]; vmax?: number }[];
  points: Record<string, { x: number; y: number; heading: number; tol: number; label: string }>;
}
