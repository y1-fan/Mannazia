import type {
  BookDetail,
  BookList,
  BookState,
  BookUpdatePayload,
  CanvasList,
  Health,
  ImportPayload,
  ImportPreview,
  ReadingProgress,
  StorageUsage,
  SystemInfo,
  DownloadJob,
  DownloadQuality,
} from './types';

const API_BASE = '/api';

export class ApiError extends Error {
  status: number;
  code: string;
  details?: Record<string, unknown>;

  constructor(
    message: string,
    status = 0,
    code = 'request_failed',
    details?: Record<string, unknown>,
  ) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.code = code;
    this.details = details;
  }
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const headers = new Headers(options.headers);
  headers.set('Accept', 'application/json');
  if (options.body && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json');
  }
  let response: Response;
  try {
    response = await fetch(`${API_BASE}${path}`, {
      credentials: 'same-origin',
      ...options,
      headers,
    });
  } catch {
    throw new ApiError(
      'Could not reach the Mannazia server. Check that the container is running.',
      0,
      'network_error',
    );
  }
  if (!response.ok) {
    let message = `Request failed (HTTP ${response.status}).`;
    let code = 'request_failed';
    let details: Record<string, unknown> | undefined;
    try {
      const body = await response.json();
      if (body?.error) {
        message = body.error.message || message;
        code = body.error.code || code;
        details = body.error.details;
      } else if (typeof body?.detail === 'string') {
        message = body.detail;
      }
    } catch {
      // Keep the HTTP fallback message.
    }
    throw new ApiError(message, response.status, code, details);
  }
  if (response.status === 204) {
    return undefined as T;
  }
  return (await response.json()) as T;
}

function jsonBody(value: unknown): string {
  return JSON.stringify(value);
}

export const api = {
  preview(manifestUrl: string): Promise<ImportPreview> {
    return request<ImportPreview>('/import/preview', {
      method: 'POST',
      body: jsonBody({ manifest_url: manifestUrl }),
    });
  },

  importBook(payload: ImportPayload): Promise<BookDetail> {
    return request<BookDetail>('/books', {
      method: 'POST',
      body: jsonBody(payload),
    });
  },

  listBooks(params: {
    query?: string;
    state?: BookState | '';
    tag?: string;
    limit?: number;
    offset?: number;
  } = {}): Promise<BookList> {
    const search = new URLSearchParams();
    if (params.query) search.set('query', params.query);
    if (params.state) search.set('state', params.state);
    if (params.tag) search.set('tag', params.tag);
    if (params.limit) search.set('limit', String(params.limit));
    if (params.offset) search.set('offset', String(params.offset));
    const suffix = search.toString() ? `?${search.toString()}` : '';
    return request<BookList>(`/books${suffix}`);
  },

  getBook(bookId: string): Promise<BookDetail> {
    return request<BookDetail>(`/books/${encodeURIComponent(bookId)}`);
  },

  updateBook(bookId: string, payload: BookUpdatePayload): Promise<BookDetail> {
    return request<BookDetail>(`/books/${encodeURIComponent(bookId)}`, {
      method: 'PATCH',
      body: jsonBody(payload),
    });
  },

  deleteBook(bookId: string): Promise<void> {
    return request<void>(`/books/${encodeURIComponent(bookId)}`, { method: 'DELETE' });
  },

  getCanvases(bookId: string): Promise<CanvasList> {
    return request<CanvasList>(`/books/${encodeURIComponent(bookId)}/canvases`);
  },

  getProgress(bookId: string): Promise<ReadingProgress> {
    return request<ReadingProgress>(`/books/${encodeURIComponent(bookId)}/progress`);
  },

  saveProgress(
    bookId: string,
    payload: { canvas_id?: string | null; source_canvas_id?: string | null; sequence_index: number },
  ): Promise<ReadingProgress> {
    return request<ReadingProgress>(`/books/${encodeURIComponent(bookId)}/progress`, {
      method: 'PUT',
      body: jsonBody(payload),
      keepalive: true,
    });
  },

  startDownload(bookId: string, quality: DownloadQuality): Promise<DownloadJob> {
    return request<DownloadJob>(`/books/${encodeURIComponent(bookId)}/downloads`, {
      method: 'POST',
      body: jsonBody({ quality }),
    });
  },

  deleteLocalCopy(bookId: string): Promise<BookDetail> {
    return request<BookDetail>(`/books/${encodeURIComponent(bookId)}/local-copy`, {
      method: 'DELETE',
    });
  },

  listDownloads(params: { bookId?: string; state?: string; limit?: number } = {}): Promise<{
    items: DownloadJob[];
    total: number;
    limit: number;
    offset: number;
  }> {
    const search = new URLSearchParams();
    if (params.bookId) search.set('book_id', params.bookId);
    if (params.state) search.set('state', params.state);
    if (params.limit) search.set('limit', String(params.limit));
    const suffix = search.toString() ? `?${search.toString()}` : '';
    return request(`/downloads${suffix}`);
  },

  getDownload(jobId: string): Promise<DownloadJob> {
    return request<DownloadJob>(`/downloads/${encodeURIComponent(jobId)}`);
  },

  pauseDownload(jobId: string): Promise<DownloadJob> {
    return request<DownloadJob>(`/downloads/${encodeURIComponent(jobId)}/pause`, {
      method: 'POST',
    });
  },

  resumeDownload(jobId: string): Promise<DownloadJob> {
    return request<DownloadJob>(`/downloads/${encodeURIComponent(jobId)}/resume`, {
      method: 'POST',
    });
  },

  cancelDownload(jobId: string): Promise<DownloadJob> {
    return request<DownloadJob>(`/downloads/${encodeURIComponent(jobId)}/cancel`, {
      method: 'POST',
    });
  },

  retryDownload(jobId: string): Promise<DownloadJob> {
    return request<DownloadJob>(`/downloads/${encodeURIComponent(jobId)}/retry`, {
      method: 'POST',
    });
  },

  storage(): Promise<StorageUsage> {
    return request<StorageUsage>('/system/storage');
  },

  systemInfo(): Promise<SystemInfo> {
    return request<SystemInfo>('/system/info');
  },

  health(): Promise<Health> {
    return request<Health>('/health');
  },
};

export function localPageUrl(bookId: string, index: number): string {
  return `${API_BASE}/books/${encodeURIComponent(bookId)}/pages/${index}`;
}

export function localCoverUrl(bookId: string): string {
  return `${API_BASE}/books/${encodeURIComponent(bookId)}/cover`;
}
