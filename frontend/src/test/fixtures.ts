import { vi } from 'vitest';
import type { BookDetail, BookSummary, CanvasItem, DownloadJob } from '../types';

export const bookSummary: BookSummary = {
  id: 'b1',
  title: 'The Book of Hours',
  creator: 'Example Atelier',
  thumbnail_url: 'https://example.org/thumb.jpg',
  local_cover_url: null,
  download_state: 'offline',
  total_canvases: 3,
  total_pages: 3,
  completed_pages: 3,
  failed_pages: 0,
  unsupported_canvases: 0,
  tags: ['prayer'],
  last_read_index: 1,
  imported_at: '2026-10-01T10:00:00Z',
  updated_at: '2026-10-02T10:00:00Z',
};

export const bookDetail: BookDetail = {
  ...bookSummary,
  manifest_url: 'https://example.org/iiif/book2/manifest',
  api_version: '3',
  description: 'A luminous book of hours.',
  language: 'Latin',
  date: '1450',
  rights: 'Permission required.',
  rights_uri: 'https://example.org/rights/inc',
  metadata: [
    { label: 'Creator', value: 'Example Atelier' },
    { label: 'Shelfmark', value: 'MS 7' },
  ],
  summary: 'A luminous book of hours.',
  provider: 'Example Library',
  required_statement: { label: 'Attribution', value: 'Image courtesy of the Example Library.' },
  homepage: [],
  rendering: [],
  see_also: [],
  structures: [],
  warnings: [],
  source_manifest_id: 'https://example.org/iiif/book2/manifest',
  last_refresh_at: '2026-10-01T10:00:00Z',
  downloaded_bytes: 1234,
  local_storage_bytes: 1234,
  archive_bytes: 0,
  active_job: null,
  latest_job: null,
};

export function canvas(index: number, overrides: Partial<CanvasItem> = {}): CanvasItem {
  return {
    id: `c${index}`,
    source_id: `https://example.org/iiif/canvas/${index}`,
    index,
    label: `Page ${index}`,
    width: 2400,
    height: 3200,
    image_url: `https://example.org/iiif/canvas/${index}/full/max/0/default.jpg`,
    thumbnail_url: `https://example.org/iiif/canvas/${index}/full/200,/0/default.jpg`,
    local_thumbnail_url: null,
    image_service_id: `https://example.org/iiif/canvas/${index}`,
    service: { id: `https://example.org/iiif/canvas/${index}`, level: 'level2' },
    unsupported: false,
    local_available: false,
    local_url: null,
    view_url: `https://example.org/iiif/canvas/${index}/full/max/0/default.jpg`,
    page_status: 'pending',
    ...overrides,
  };
}

export const job: DownloadJob = {
  id: 'job1234567890',
  book_id: 'b1',
  book_title: 'The Book of Hours',
  state: 'completed',
  quality: 'research',
  total_pages: 3,
  completed_pages: 3,
  failed_pages: 0,
  bytes_downloaded: 123400,
  progress_percent: 100,
  error: null,
  created_at: '2026-10-01T10:00:00Z',
  updated_at: '2026-10-01T10:05:00Z',
  completed_at: '2026-10-01T10:05:00Z',
};

export function jsonResponse(data: unknown, status = 200): Response {
  return new Response(JSON.stringify(data), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

type RouteHandler = (init?: RequestInit) => Response | Promise<Response>;

export function installFetch(routes: Record<string, RouteHandler>) {
  const mock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === 'string' ? input : input.toString();
    const method = (init?.method ?? 'GET').toUpperCase();
    const key = `${method} ${url}`;
    const handler = routes[key] ?? routes[url];
    if (!handler) {
      throw new Error(`Unexpected fetch: ${key}`);
    }
    return handler(init);
  });
  vi.stubGlobal('fetch', mock);
  return mock;
}
