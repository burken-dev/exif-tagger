export interface GalleryImage {
  id: number | null;
  filename: string;
  relative_path: string;
  file_path?: string;
  tags: string[];
  indexed: boolean;
  last_modified?: number;
  created_at?: string;
  updated_at?: string;
}

export interface FolderItem {
  name: string;
  relative_path: string;
}

export interface FolderBreadcrumb {
  name: string;
  path: string;
}

export interface FoldersResponse {
  current_path: string;
  breadcrumbs: FolderBreadcrumb[];
  folders: FolderItem[];
}

export interface LogItem {
  id: number;
  text: string;
  type: string;
  level?: string;
}

export interface ProcessingStatus {
  running: boolean;
  stopRequested?: boolean;
  total?: number;
  processed?: number;
  progressPct?: number;
  summary?: {
    failed: number;
    errors?: any[];
  } | null;
  logs?: LogItem[];
}

export interface TagConfig {
  description?: string;
  threshold?: number;
}

export interface ModelConfig {
  base_url: string;
  model_name: string;
  max_tokens: number;
  temperature: number;
  api_key?: string;
  use_structured_outputs?: boolean;
  max_image_dimension?: number;
  image_format?: 'webp' | 'jpeg';
  image_quality?: number;
  concurrency?: number;
  params?: Record<string, any>;
}

export interface GuardrailConfig {
  enabled?: boolean;
  max_matched_tags?: number;
  on_overflow?: 'suppress' | 'top_k' | 'warn';
}

export interface AppConfig {
  root_directory: string;
  model: ModelConfig;
  tags: Record<string, TagConfig>;
  guardrails?: GuardrailConfig;
  exclude_patterns: string[];
  log_level?: string;
  log_dir?: string;
}

export interface ScheduleItem {
  id: string;
  name: string;
  folder: string;
  cron_expression?: string;
  interval_hours?: number;
  last_run_at?: string;
  last_status?: string;
  next_run_at?: string;
  enabled?: boolean;
  max_images?: number;
}

export interface CreateSchedulePayload {
  name: string;
  folder: string;
  interval_hours?: number;
  cron_expression?: string;
  enabled?: boolean;
  max_images?: number;
}
