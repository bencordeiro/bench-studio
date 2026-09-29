export type GradingMode = "deterministic" | "judge" | "hybrid" | "manual" | "execution";

export type RunStatus =
  | "queued"
  | "preparing"
  | "warming_up"
  | "running_target"
  | "running_deterministic"
  | "running_judge"
  | "running_verifier"
  | "completed"
  | "completed_with_errors"
  | "cancel_requested"
  | "cancelled"
  | "interrupted"
  | "failed";

export type PromptStatus =
  | "pending"
  | "running"
  | "completed"
  | "failed"
  | "skipped"
  | "cancelled"
  | "awaiting_judge"
  | "awaiting_manual";

export interface HealthResponse {
  status: string;
  version: string;
  python_version: string;
  platform: string;
  db_path: string;
  data_dir: string;
  frontend_built: boolean;
}

export interface EndpointProfile {
  id: string;
  name: string;
  base_url: string;
  default_model: string;
  request_timeout: number;
  verify_tls: boolean;
  custom_headers: Record<string, unknown>;
  extra_body_params: Record<string, unknown>;
  enabled: boolean;
  notes: string;
  has_api_key: boolean;
  api_key_storage: string;
  api_key_env_var: string;
  input_price_per_1m: number;
  output_price_per_1m: number;
  masked_api_key?: string | null;
  created_at?: string;
  updated_at?: string;
}

export interface ConnectionTestResult {
  reachable: boolean;
  http_status: number | null;
  response_time_ms: number | null;
  models_discovered: boolean;
  model_count: number;
  models: string[];
  completion_checked?: boolean;
  completion_ok?: boolean;
  completion_model?: string | null;
  error: string | null;
  sanitized: boolean;
}

export interface FetchModelsResult {
  success: boolean;
  models: string[];
  error: string | null;
}

export interface PromptMessage {
  role: "system" | "user" | "assistant";
  content: string;
  position?: number;
}

export interface GenerationOverrides {
  temperature?: number | null;
  top_p?: number | null;
  max_tokens?: number | null;
  stop?: string[] | null;
  seed?: number | null;
}

export interface BenchmarkPrompt {
  id?: string;
  benchmark_id?: string;
  stable_id: string;
  title: string;
  description: string;
  category: string;
  tags: string[];
  difficulty: string;
  importance_weight: number;
  position: number;
  enabled: boolean;
  grading_mode: GradingMode;
  generation_overrides: GenerationOverrides;
  grader_config: Record<string, unknown>;
  messages: PromptMessage[];
  created_at?: string;
  updated_at?: string;
}

export interface BenchmarkSetSummary {
  id: string;
  name: string;
  description: string;
  version: string;
  tags: string[];
  is_example: boolean;
  show_in_leaderboards: boolean;
  prompt_count: number;
  enabled_prompt_count: number;
  created_at?: string;
  updated_at?: string;
}

export interface BenchmarkSet {
  id: string;
  name: string;
  description: string;
  version: string;
  tags: string[];
  scoring_config: Record<string, unknown>;
  performance_thresholds: Record<string, unknown>;
  composite_weights: Record<string, unknown>;
  is_example: boolean;
  show_in_leaderboards: boolean;
  prompts: BenchmarkPrompt[];
  created_at?: string;
  updated_at?: string;
}

export type LeaderboardBasis = "best" | "mean" | "latest";
export type LeaderboardSort = "quality" | "performance" | "composite" | "reliability";

export interface LeaderboardSuiteSummary {
  suite_id: string;
  suite_name: string;
  suite_version: string;
  run_count: number;
  model_count: number;
  top_model: string | null;
  top_quality_score: number | null;
  last_run_at: string | null;
}

export interface LeaderboardEntry {
  rank: number;
  model: string;
  run_count: number;
  run_ids: string[];
  /** Run whose scores the ranking reflects (basis-aware); use for deep compare. */
  representative_run_id: string;
  target_endpoint_names: string[];
  quality_score: number | null;
  reliability_score: number | null;
  performance_index: number | null;
  composite_score: number | null;
  last_run_at: string | null;
}

export interface LeaderboardResponse {
  suite_id: string;
  suite_name: string;
  suite_version: string;
  scoring_basis: LeaderboardBasis;
  sort_metric: LeaderboardSort;
  total_runs: number;
  entries: LeaderboardEntry[];
  warnings: string[];
}

export interface RunConfig {
  repetitions: number;
  sequential_execution: boolean;
  shuffle_prompt_order: boolean;
  warm_up_request: boolean;
  streaming_enabled: boolean;
  judge_verification_enabled: boolean;
  temperature: number;
  top_p: number;
  max_tokens: number;
  reasoning_effort?: string;
  timeout: number;
  retry_max_attempts?: number;
  retry_backoff_base?: number;
  retry_backoff_max?: number;
}

export interface RunSummary {
  id: string;
  name: string;
  status: RunStatus;
  target_model: string;
  target_endpoint_name: string;
  benchmark_name: string | null;
  total_prompts: number;
  completed_prompts: number;
  failed_prompts: number;
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
  quality_score: number | null;
  reliability_score: number | null;
  performance_index: number | null;
  composite_score: number | null;
  total_cost: number | null;
}

export interface RunResponse {
  id: string;
  name: string;
  notes: string;
  status: RunStatus;
  benchmark_id: string;
  target_endpoint_id: string | null;
  target_endpoint_name: string;
  target_model: string;
  judge_endpoint_id: string | null;
  judge_endpoint_name: string;
  judge_model: string;
  judge_enabled: boolean;
  verifier_enabled: boolean;
  run_config: RunConfig;
  summary: RunSummaryData;
  error_message: string;
  total_prompts: number;
  completed_prompts: number;
  failed_prompts: number;
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
}

export interface RunSummaryData {
  quality_score?: number | null;
  reliability_score?: number | null;
  performance_index?: number | null;
  composite_score?: number | null;
  scoring_coverage?: string;
  scored_count?: number;
  total_count?: number;
  category_scores?: Record<string, number>;
  repetition?: Record<string, number | null>;
  total_cost?: number | null;
}

export interface ExecutionDetail {
  id: string;
  run_id: string;
  prompt_snapshot_id: string;
  position: number;
  repetition: number;
  status: PromptStatus;
  final_score: number | null;
  max_score: number;
  error_message: string;
  title: string;
  category: string;
  grading_mode: GradingMode;
  importance_weight: number;
  messages: PromptMessage[];
  candidate_response: string;
  reasoning_response?: string;
  generation_diagnostics?: {
    no_final_answer?: boolean;
    possible_repetition?: boolean;
    answer_chars?: number;
    reasoning_chars?: number;
    truncated?: boolean;
  };
  reference_answer: string;
  finish_reason: string;
  timing: {
    time_to_first_token?: number | null;
    total_response_time?: number | null;
    output_tokens_per_second?: number | null;
    completion_tokens?: number | null;
    prompt_tokens?: number | null;
    truncated?: boolean;
    /** "server" = the backend's own generation rate (excludes prefill/network). */
    tps_source?: "server" | "computed";
    prompt_tokens_per_second?: number | null;
    cost?: number | null;
  };
  deterministics: DeterministicView[];
  judge: JudgeView | null;
  verifier: VerifierView | null;
  manual: ManualView | null;
  raw_meta: { http_status: number | null; retry_count: number; tokens_estimated: boolean };
}

export interface DeterministicView {
  type: string;
  passed: boolean;
  score: number;
  max_score: number;
  details: Record<string, unknown>;
}

export interface JudgeView {
  final_score: number;
  raw_total: number | null;
  critical_error: boolean;
  score_cap: number | null;
  confidence: number | null;
  dimension_scores: Record<string, { score: number; maximum: number; reason: string }>;
  strengths: string[];
  deductions: { points: number; reason: string; candidate_evidence?: string }[];
  valid: boolean;
}

export interface VerifierView {
  original_score: number;
  verified_score: number;
  adjusted: boolean;
  confidence: number | null;
  adjustment_reason: string;
  problems_found: string[];
  valid: boolean;
}

export interface ManualView {
  score: number;
  notes: string;
  dimension_scores: Record<string, number>;
}

export interface RunResults {
  run: RunResponse;
  summary: RunSummaryData;
  executions: ExecutionDetail[];
  charts: Record<string, unknown>;
  coverage: { scored: number; total: number; label: string };
}

export interface AppSettings {
  local_data_path: string;
  log_level: string;
  default_timeout: number;
  default_retry_max_attempts: number;
  default_retry_backoff_base: number;
  default_retry_backoff_max: number;
  default_temperature: number;
  default_top_p: number;
  default_max_tokens: number;
  composite_weights: { quality: number; reliability: number; performance: number };
  automatic_backup: boolean;
  launch_browser: boolean;
  theme: string;
  allow_plaintext_key_fallback: boolean;
  keyring_available: boolean;
}
