import type { BookState, JobState } from './types';
import type { Language, Translate, TranslationKey } from './i18n';

export interface StateMeta {
  label: string;
  description: string;
  tone: string;
}

const BOOK_STATE_META_KEYS: Record<
  BookState,
  { label: TranslationKey; description: TranslationKey; tone: string }
> = {
  online: {
    label: 'state.online.label',
    description: 'state.online.description',
    tone: 'online',
  },
  queued: {
    label: 'state.queued.label',
    description: 'state.queued.description',
    tone: 'working',
  },
  downloading: {
    label: 'state.downloading.label',
    description: 'state.downloading.description',
    tone: 'working',
  },
  paused: {
    label: 'state.paused.label',
    description: 'state.paused.description',
    tone: 'muted',
  },
  partial: {
    label: 'state.partial.label',
    description: 'state.partial.description',
    tone: 'partial',
  },
  offline: {
    label: 'state.offline.label',
    description: 'state.offline.description',
    tone: 'offline',
  },
  error: {
    label: 'state.error.label',
    description: 'state.error.description',
    tone: 'error',
  },
};

const JOB_STATE_META_KEYS: Record<
  JobState,
  { label: TranslationKey; description: TranslationKey; tone: string }
> = {
  queued: {
    label: 'job.queued.label',
    description: 'job.queued.description',
    tone: 'working',
  },
  downloading: {
    label: 'job.downloading.label',
    description: 'job.downloading.description',
    tone: 'working',
  },
  paused: {
    label: 'job.paused.label',
    description: 'job.paused.description',
    tone: 'muted',
  },
  completed: {
    label: 'job.completed.label',
    description: 'job.completed.description',
    tone: 'offline',
  },
  failed: {
    label: 'job.failed.label',
    description: 'job.failed.description',
    tone: 'error',
  },
  cancelled: {
    label: 'job.cancelled.label',
    description: 'job.cancelled.description',
    tone: 'muted',
  },
};

export function bookStateMeta(state: BookState, t: Translate): StateMeta {
  const meta = BOOK_STATE_META_KEYS[state];
  return { label: t(meta.label), description: t(meta.description), tone: meta.tone };
}

export function jobStateMeta(state: JobState, t: Translate): StateMeta {
  const meta = JOB_STATE_META_KEYS[state];
  return { label: t(meta.label), description: t(meta.description), tone: meta.tone };
}

export function formatBytes(bytes: number | null | undefined): string {
  if (!bytes || bytes <= 0) return '0 B';
  const units = ['B', 'KB', 'MB', 'GB', 'TB', 'PB'];
  let value = bytes;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit += 1;
  }
  const precision = value >= 100 || unit === 0 ? 0 : value >= 10 ? 1 : 2;
  return `${value.toFixed(precision)} ${units[unit]}`;
}

export function formatDate(value: string | null | undefined, locale = 'en-GB'): string {
  if (!value) return '—';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleDateString(locale, {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
  });
}

export function formatDateTime(
  value: string | null | undefined,
  locale = 'en-GB',
): string {
  if (!value) return '—';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString(locale, {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  });
}

export function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value));
}

export function bookProgressPercent(completed: number, total: number): number {
  if (!total) return 0;
  return Math.round((completed / total) * 100);
}

export function classNames(...values: Array<string | false | null | undefined>): string {
  return values.filter(Boolean).join(' ');
}

export function parseTagInput(value: string): string[] {  return Array.from(
    new Set(
      value
        .split(/[,;]/)
        .map((part) => part.trim())
        .filter(Boolean),
    ),
  ).slice(0, 20);
}

export function describeError(error: unknown): string {
  if (error instanceof Error) return error.message;
  if (typeof error === 'string') return error;
  return 'An unexpected error occurred.';
}

export function safeHttpUrl(value: string | null | undefined): string | undefined {
  if (!value) return undefined;
  try {
    const url = new URL(value);
    return url.protocol === 'http:' || url.protocol === 'https:' ? url.toString() : undefined;
  } catch {
    return undefined;
  }
}

export function pageLabel(
  label: string | null | undefined,
  index: number,
  t: Translate,
): string {
  const value = (label ?? '').trim();
  if (
    !value ||
    /^[-–—.·\s]+$/.test(value) ||
    /^(untitled|n\/a|none)$/i.test(value) ||
    value === String(index) ||
    value === `Page ${index}` ||
    value === `第 ${index} 页`
  ) {
    return t('common.pageLabel', { index });
  }
  return value;
}

export function stateDescription(state: BookState, t: Translate): string {
  return bookStateMeta(state, t).description;
}

/** Translate the stable diagnostics the backend stores with a book or job. */
export function localizeDiagnostic(
  message: string | null | undefined,
  t: Translate,
  language: Language,
): string {
  if (!message || language !== 'zh') return message ?? '';
  const value = message.trim();

  if (value === 'The Manifest has no title; a placeholder title was used.') {
    return t('diagnostic.noTitle');
  }
  if (value === 'Some page images use ordinary image URLs without a IIIF Image API service.') {
    return t('diagnostic.ordinaryImages');
  }
  if (value === 'The Manifest has multiple sequences; only the first is used.') {
    return t('diagnostic.multipleSequences');
  }
  if (value.startsWith('No supported image resources were found.')) {
    return t('diagnostic.noImages');
  }
  if (value === 'No cover page could be selected.') {
    return t('diagnostic.noCoverSelected');
  }
  if (value === 'The selected cover page has no image resource.') {
    return t('diagnostic.coverNoImage');
  }
  if (value === 'Download was interrupted by an application restart.') {
    return t('diagnostic.interruptedRestart');
  }
  if (value === 'Download was interrupted by application shutdown.') {
    return t('diagnostic.interruptedShutdown');
  }
  if (
    value ===
    'Image processing failed for some pages; the original source image was stored instead.'
  ) {
    return t('diagnostic.processingFailed');
  }

  let match = value.match(/^Cover image could not be cached: (.*)$/s);
  if (match) return t('diagnostic.coverFailed', { detail: match[1] });

  match = value.match(
    /^(\d+) of (\d+) canvases have no primary image\. A complete offline copy will not be possible for those pages\.$/,
  );
  if (match) {
    return t('diagnostic.canvasesWithoutImage', {
      count: match[1],
      total: match[2],
    });
  }

  match = value.match(
    /^(\d+) page image\(s\) have no IIIF Image API service; the ordinary image URL will be used\.$/,
  );
  if (match) return t('diagnostic.noImageService', { count: match[1] });

  match = value.match(
    /^Some canvases contain more than one image resource\. Only the primary image of each canvas is read or downloaded \(first seen on canvas (\d+)\.\)$/,
  );
  if (match) return t('diagnostic.multipleImages', { canvas: match[1] });

  match = value.match(/^Canvas (\d+) has no supported painting image\.$/);
  if (match) return t('diagnostic.canvasNoImage', { index: match[1] });

  match = value.match(
    /^Canvas (\d+) has no identifier; sequence position will be used\.$/,
  );
  if (match) return t('diagnostic.canvasNoId', { index: match[1] });

  match = value.match(
    /^(\d+) external AnnotationPage\(s\) are not embedded in the Manifest; they were not fetched\.$/,
  );
  if (match) return t('diagnostic.externalAnnotations', { count: match[1] });

  match = value.match(
    /^(\d+) page\(s\) failed\. Completed pages remain available; retry failed pages or resume later\.$/,
  );
  if (match) return t('diagnostic.pagesFailed', { count: match[1] });

  return value;
}
