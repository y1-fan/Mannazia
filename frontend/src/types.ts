export type BookState =
  | 'online'
  | 'queued'
  | 'downloading'
  | 'paused'
  | 'partial'
  | 'offline'
  | 'error';

export type JobState =
  | 'queued'
  | 'downloading'
  | 'paused'
  | 'completed'
  | 'failed'
  | 'cancelled';

export type DownloadQuality = 'reading' | 'standard' | 'appreciation' | 'research';
export type JobQuality = DownloadQuality | 'legacy';

export interface MetadataEntry {
  label: string;
  value: string;
}

export interface BookSummary {
  id: string;
  title: string;
  creator: string | null;
  thumbnail_url: string | null;
  local_cover_url: string | null;
  download_state: BookState;
  total_canvases: number;
  total_pages: number;
  completed_pages: number;
  failed_pages: number;
  unsupported_canvases: number;
  tags: string[];
  last_read_index: number;
  imported_at: string;
  updated_at: string;
}

export interface LinkResource {
  id?: string | null;
  label?: string | null;
  format?: string | null;
  type?: string | null;
}

export interface StructureNode {
  id?: string | null;
  label: string;
  depth: number;
  canvas_ids: string[];
}

export interface DownloadJob {
  id: string;
  book_id: string;
  book_title: string | null;
  state: JobState;
  quality: JobQuality;
  total_pages: number;
  completed_pages: number;
  failed_pages: number;
  bytes_downloaded: number;
  progress_percent: number;
  error: string | null;
  created_at: string;
  updated_at: string;
  completed_at: string | null;
}

export interface BookDetail extends BookSummary {
  manifest_url: string;
  api_version: string;
  description: string | null;
  language: string | null;
  date: string | null;
  rights: string | null;
  rights_uri: string | null;
  metadata: MetadataEntry[];
  summary: string;
  provider: string;
  required_statement: Record<string, string>;
  homepage: LinkResource[];
  rendering: LinkResource[];
  see_also: LinkResource[];
  structures: StructureNode[];
  warnings: string[];
  source_manifest_id: string | null;
  last_refresh_at: string | null;
  downloaded_bytes: number;
  local_storage_bytes: number;
  archive_bytes: number;
  active_job: DownloadJob | null;
  latest_job: DownloadJob | null;
}

export interface BookList {
  items: BookSummary[];
  total: number;
  limit: number;
  offset: number;
}

export interface ImageServiceInfo {
  id: string;
  type?: string | null;
  profile?: unknown;
  level?: string | null;
  formats?: string[];
  qualities?: string[];
  sizes?: Array<{ width: number; height: number }>;
}

export interface CanvasItem {
  id: string;
  source_id: string | null;
  index: number;
  label: string;
  width: number | null;
  height: number | null;
  image_url: string | null;
  thumbnail_url: string | null;
  local_thumbnail_url: string | null;
  image_service_id: string | null;
  service: ImageServiceInfo | null;
  unsupported: boolean;
  local_available: boolean;
  local_url: string | null;
  view_url: string | null;
  page_status: string;
}

export interface CanvasList {
  book_id: string;
  download_state: BookState;
  total: number;
  items: CanvasItem[];
}

export interface ReadingProgress {
  book_id: string;
  canvas_id: string | null;
  source_canvas_id: string | null;
  sequence_index: number;
  updated_at: string | null;
}

export interface ImportPreview {
  manifest_url: string;
  api_version: string;
  title: string;
  creator: string;
  description: string;
  language: string;
  date: string;
  rights: string;
  rights_uri: string;
  required_statement: Record<string, string>;
  thumbnail_url: string | null;
  canvas_count: number;
  image_canvas_count: number;
  metadata: MetadataEntry[];
  summary: string;
  provider: string;
  homepage: LinkResource[];
  rendering: LinkResource[];
  warnings: string[];
  preview_token: string | null;
  duplicate_of: string | null;
  duplicate_title: string | null;
}

export interface StorageUsage {
  books_bytes: number;
  data_bytes: number;
  config_bytes: number;
  database_bytes: number;
  book_count: number;
  book_file_count: number;
  free_bytes: number;
  total_bytes: number;
}

export interface SystemInfo {
  name: string;
  version: string;
  environment: string;
  download_concurrency: number;
  download_max_width: number;
  cover_max_width: number;
  download_image_format: string;
  max_manifest_bytes: number;
  max_image_bytes: number;
  allowed_private_host_count: number;
  allow_private_networks: boolean;
  auto_resume_downloads: boolean;
  security_notice: string;
}

export interface Health {
  status: string;
  version: string;
  database: string;
  books_directory: string;
  active_downloads: number;
}

export interface BookUpdatePayload {
  title?: string;
  creator?: string | null;
  description?: string | null;
  language?: string | null;
  date?: string | null;
  rights?: string | null;
  rights_uri?: string | null;
  tags?: string[];
}

export interface ImportPayload {
  manifest_url: string;
  preview_token?: string | null;
  title?: string;
  creator?: string;
  description?: string;
  language?: string;
  date?: string;
  rights?: string;
  rights_uri?: string;
  tags?: string[];
}
