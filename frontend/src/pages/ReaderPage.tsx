import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { FormEvent } from 'react';
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom';
import type OpenSeadragon from 'openseadragon';
import { api } from '../api';
import { StateBadge } from '../components/StateBadge';
import { Callout, ErrorPanel, LoadingBlock } from '../components/Feedback';
import { Icon } from '../components/Icon';
import { OpenSeadragonViewer, type ViewerTileSource } from '../components/OpenSeadragonViewer';
import { LanguageSwitch } from '../components/LanguageSwitch';
import { useAsync, useDocumentTitle } from '../hooks';
import { bookStateMeta, clamp, pageLabel } from '../lib';
import { useErrorMessage, useI18n } from '../i18n';
import type { BookDetail, CanvasItem } from '../types';

const PRELOAD_RADIUS = 2;
const THUMBNAILS_VISIBLE_KEY = 'mannazia.reader.thumbnails';

export function ReaderPage() {
  const { t } = useI18n();
  const errorMessage = useErrorMessage();
  const { bookId = '' } = useParams();
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const [current, setCurrent] = useState<number | null>(null);
  const [viewer, setViewer] = useState<OpenSeadragon.Viewer | null>(null);
  const [viewerError, setViewerError] = useState<string | null>(null);
  const [viewerReady, setViewerReady] = useState(false);
  const [imageError, setImageError] = useState(false);
  const [saveState, setSaveState] = useState<'idle' | 'saving' | 'error'>('idle');
  const [pageInput, setPageInput] = useState('1');
  const [isFullscreen, setIsFullscreen] = useState(false);
  const [showThumbnails, setShowThumbnails] = useState(() => {
    try {
      return window.localStorage.getItem(THUMBNAILS_VISIBLE_KEY) !== 'hidden';
    } catch {
      return true;
    }
  });
  const stageRef = useRef<HTMLDivElement>(null);
  const thumbRefs = useRef<Record<number, HTMLButtonElement | null>>({});
  const progressRef = useRef<{
    bookId: string;
    canvases: CanvasItem[];
    current: number | null;
  }>({ bookId, canvases: [], current: null });

  const { data, loading, error, reload } = useAsync(
    async () => {
      const [book, canvases, progress] = await Promise.all([
        api.getBook(bookId),
        api.getCanvases(bookId),
        api.getProgress(bookId),
      ]);
      return { book, canvases: canvases.items, progress };
    },
    bookId,
  );

  const book: BookDetail | null = data?.book ?? null;
  const canvases = useMemo(() => data?.canvases ?? [], [data]);
  useDocumentTitle(
    book ? t('reader.readingTitle', { title: book.title }) : t('reader.book'),
  );

  useEffect(() => {
    if (!data || current !== null) return;
    let initial = data.progress.sequence_index ?? 0;
    const requested = Number(searchParams.get('page'));
    if (Number.isFinite(requested) && requested >= 1) {
      initial = requested - 1;
    }
    setCurrent(clamp(initial, 0, Math.max(0, canvases.length - 1)));
    // Only initialize once, when the remote data first arrives.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data]);

  progressRef.current = { bookId, canvases, current };

  useEffect(() => {
    setViewerError(null);
    setViewerReady(false);
    setImageError(false);
  }, [current]);

  useEffect(() => {
    if (current === null) return;
    setPageInput(String(current + 1));
    const canvas = canvases[current];
    if (!canvas || !book) return;
    setSaveState('saving');
    const timer = window.setTimeout(() => {
      void api
        .saveProgress(book.id, {
          canvas_id: canvas.id,
          source_canvas_id: canvas.source_id,
          sequence_index: current,
        })
        .then(() => setSaveState('idle'))
        .catch(() => setSaveState('error'));
    }, 450);
    return () => window.clearTimeout(timer);
  }, [current, bookId, canvases, book]);

  useEffect(() => {
    const state = progressRef.current;
    return () => {
      if (!state.bookId || state.current === null) return;
      const canvas = state.canvases[state.current];
      if (!canvas) return;
      void api
        .saveProgress(state.bookId, {
          canvas_id: canvas.id,
          source_canvas_id: canvas.source_id,
          sequence_index: state.current,
        })
        .catch(() => undefined);
    };
  }, []);

  const goTo = useCallback(
    (index: number) => {
      if (!canvases.length) return;
      const next = clamp(index, 0, canvases.length - 1);
      setCurrent(next);
      setSearchParams({ page: String(next + 1) }, { replace: true });
    },
    [canvases.length, setSearchParams],
  );

  const next = useCallback(() => {
    if (current !== null) goTo(current + 1);
  }, [current, goTo]);

  const previous = useCallback(() => {
    if (current !== null) goTo(current - 1);
  }, [current, goTo]);

  const zoomIn = useCallback(() => viewer?.viewport.zoomBy(1.35), [viewer]);
  const zoomOut = useCallback(() => viewer?.viewport.zoomBy(1 / 1.35), [viewer]);
  const fit = useCallback(() => viewer?.viewport.goHome(), [viewer]);

  const toggleFullscreen = useCallback(() => {
    const element = stageRef.current;
    if (!element) return;
    if (document.fullscreenElement) {
      void document.exitFullscreen();
    } else if (element.requestFullscreen) {
      void element.requestFullscreen().catch(() => undefined);
    }
  }, []);

  useEffect(() => {
    const handler = () => setIsFullscreen(Boolean(document.fullscreenElement));
    document.addEventListener('fullscreenchange', handler);
    return () => document.removeEventListener('fullscreenchange', handler);
  }, []);

  useEffect(() => {
    try {
      window.localStorage.setItem(
        THUMBNAILS_VISIBLE_KEY,
        showThumbnails ? 'visible' : 'hidden',
      );
    } catch {
      // Private browsing may block storage; the in-memory choice still applies.
    }
  }, [showThumbnails]);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null;
      if (
        target &&
        (target.tagName === 'INPUT' ||
          target.tagName === 'TEXTAREA' ||
          target.isContentEditable)
      ) {
        return;
      }
      if (event.key === 'ArrowLeft' || event.key === 'PageUp') {
        event.preventDefault();
        previous();
      } else if (event.key === 'ArrowRight' || event.key === 'PageDown') {
        event.preventDefault();
        next();
      } else if (event.key === 'Home') {
        event.preventDefault();
        goTo(0);
      } else if (event.key === 'End') {
        event.preventDefault();
        goTo(canvases.length - 1);
      } else if (event.key === '+' || event.key === '=') {
        zoomIn();
      } else if (event.key === '-') {
        zoomOut();
      } else if (event.key === 'f') {
        toggleFullscreen();
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [previous, next, goTo, canvases.length, toggleFullscreen, viewer, zoomIn, zoomOut]);

  useEffect(() => {
    if (current === null || !showThumbnails) return;
    const ref = thumbRefs.current[current];
    if (!ref) return;
    const reduced = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;
    ref.scrollIntoView({
      behavior: reduced ? 'auto' : 'smooth',
      inline: 'center',
      block: 'nearest',
    });
  }, [current, showThumbnails]);

  useEffect(() => {
    if (current === null) return;
    const preloads: HTMLImageElement[] = [];
    for (let offset = 1; offset <= PRELOAD_RADIUS; offset += 1) {
      for (const index of [current + offset, current - offset]) {
        const canvas = canvases[index];
        if (!canvas) continue;
        const src =
          canvas.local_thumbnail_url ?? canvas.thumbnail_url ?? canvas.local_url;
        if (!src) continue;
        const image = new Image();
        image.referrerPolicy = 'no-referrer';
        image.src = src;
        preloads.push(image);
      }
    }
    return () => {
      preloads.length = 0;
    };
  }, [current, canvases]);

  if (loading && !data) {
    return (
      <div className="reader-shell">
        <div className="reader-loading">
          <LoadingBlock label={t('reader.loading')} />
        </div>
      </div>
    );
  }

  if (error || !book || !canvases.length) {
    return (
      <div className="reader-shell">
        <header className="reader-topbar">
          <Link to={book ? `/books/${book.id}` : '/'} className="reader-back">
            <Icon name="arrow-left" size={18} />
            {book ? t('reader.book') : t('reader.library')}
          </Link>
          <LanguageSwitch compact />
        </header>
        <div className="reader-loading">
          <ErrorPanel
            title={t('reader.errorTitle')}
            message={error ? errorMessage(error) : t('reader.noPages')}
            onRetry={reload}
          />
          <Link className="button button-secondary" to="/">
            {t('reader.returnLibrary')}
          </Link>
        </div>
      </div>
    );
  }

  const index = current ?? 0;
  const canvas = canvases[index];
  const meta = bookStateMeta(book.download_state, t);
  const currentLabel = pageLabel(canvas.label, index + 1, t);
  const fallbackLabel = t('common.pageLabel', { index: index + 1 });
  const hasSourceLabel = currentLabel !== fallbackLabel;
  const localSrc = canvas.local_available ? canvas.local_url : null;
  const imageSrc = localSrc ?? canvas.image_url;
  const serviceId = canvas.image_service_id;
  const useImageService = !localSrc && Boolean(serviceId && /^https?:/i.test(serviceId));
  const tileSources: ViewerTileSource | null = useImageService
    ? `${serviceId!.replace(/\/info\.json$/i, '')}/info.json`
    : imageSrc
      ? { type: 'image', url: imageSrc }
      : null;
  const sourceKey = `${canvas.id}|${tileSources ? JSON.stringify(tileSources) : 'none'}`;
  const placeholderSrc =
    canvas.local_thumbnail_url ?? canvas.thumbnail_url ?? localSrc ?? null;
  const offlinePageWarning =
    book.download_state === 'offline' && !canvas.local_available && canvas.image_url;

  const submitPage = (event: FormEvent) => {
    event.preventDefault();
    const parsed = Number(pageInput);
    if (Number.isFinite(parsed)) goTo(parsed - 1);
  };

  return (
    <div className="reader-shell">
      <header className="reader-topbar">
        <div className="reader-topbar-left">
          <Link to={`/books/${book.id}`} className="reader-back">
            <Icon name="arrow-left" size={18} />
            <span>{t('reader.book')}</span>
          </Link>
          <div className="reader-title-block">
            <span className="reader-title">{book.title}</span>
            <span className="reader-subtitle">
              {hasSourceLabel
                ? t('reader.pageSubtitle', {
                    label: currentLabel,
                    current: index + 1,
                    total: canvases.length,
                  })
                : t('reader.pageSubtitlePlain', {
                    current: index + 1,
                    total: canvases.length,
                  })}
            </span>
          </div>
        </div>
        <div className="reader-topbar-right">
          <StateBadge state={book.download_state} />
          <LanguageSwitch compact />
          <span className={`save-state save-${saveState}`} role="status" aria-live="polite">
            {saveState === 'saving'
              ? t('reader.saving')
              : saveState === 'error'
                ? t('reader.saveError')
                : t('reader.saved')}
          </span>
        </div>
      </header>

      <div className="reader-topnav">
        <div className="reader-nav">
          <button
            type="button"
            className="reader-nav-button"
            onClick={previous}
            disabled={index === 0}
            aria-label={t('reader.previous')}
          >
            <Icon name="chevron-left" size={20} />
            <span>{t('reader.previous')}</span>
          </button>
          <form className="page-jump" onSubmit={submitPage}>
            <label htmlFor="page-number">{t('reader.page')}</label>
            <input
              id="page-number"
              type="number"
              min={1}
              max={canvases.length}
              value={pageInput}
              onChange={(event) => setPageInput(event.target.value)}
            />
            <span className="page-total">
              {t('reader.ofTotal', { total: canvases.length })}
            </span>
          </form>
          <button
            type="button"
            className="reader-nav-button"
            onClick={next}
            disabled={index === canvases.length - 1}
            aria-label={t('reader.next')}
          >
            <span>{t('reader.next')}</span>
            <Icon name="chevron-right" size={20} />
          </button>
        </div>
      </div>

      <div className="reader-stage" ref={stageRef}>
        <div className="reader-canvas-area">
          {offlinePageWarning ? (
            <div className="reader-overlay-note">
              <Callout tone="warning" title={t('reader.localMissingTitle')}>
                {t('reader.localMissingCopy')}
              </Callout>
            </div>
          ) : null}

          {canvas.unsupported || !tileSources ? (
            <div className="reader-unsupported">
              <span className="unsupported-rune" aria-hidden="true">
                ᛗ
              </span>
              <h2>{t('reader.unsupportedTitle')}</h2>
              <p>{t('reader.unsupportedCopy')}</p>
            </div>
          ) : viewerError || imageError ? (
            <div className="reader-image-fallback">
              {imageSrc && !imageError ? (
                <img
                  src={imageSrc}
                  alt={currentLabel}
                  referrerPolicy="no-referrer"
                  onError={() => setImageError(true)}
                />
              ) : (
                <div className="reader-unsupported">
                  <h2>{t('reader.imageErrorTitle')}</h2>
                  <p>
                    {viewerError
                      ? t('reader.serviceError', { message: viewerError })
                      : t('reader.remoteUnavailable')}
                  </p>
                  {localSrc ? null : (
                    <p className="muted">{t('reader.downloadHint')}</p>
                  )}
                </div>
              )}
            </div>
          ) : (
            <OpenSeadragonViewer
              key={sourceKey}
              tileSources={tileSources}
              sourceKey={sourceKey}
              label={t('reader.pageLabel', {
                index: index + 1,
                label: currentLabel,
              })}
              onReady={(viewerInstance) => {
                setViewer(viewerInstance);
              }}
              onTileLoaded={() => setViewerReady(true)}
              onError={(message) => setViewerError(message)}
            />
          )}

          {tileSources &&
          !viewerReady &&
          !viewerError &&
          !canvas.unsupported &&
          placeholderSrc ? (
            <img
              src={placeholderSrc}
              alt=""
              className="reader-page-placeholder"
              referrerPolicy="no-referrer"
            />
          ) : null}

          {tileSources && !viewerReady && !viewerError && !canvas.unsupported ? (
            <div className="reader-viewer-loading" role="status">
              <span className="spinner" aria-hidden="true" />
              <span>{t('reader.loadingPage')}</span>
            </div>
          ) : null}

          <div className="reader-floating-controls" aria-label={t('reader.imageControls')}>
            <button
              type="button"
              className="reader-control"
              onClick={zoomOut}
              aria-label={t('reader.zoomOut')}
            >
              <Icon name="zoom-out" size={18} />
            </button>
            <button
              type="button"
              className="reader-control"
              onClick={fit}
              aria-label={t('reader.fit')}
            >
              <Icon name="fit" size={18} />
            </button>
            <button
              type="button"
              className="reader-control"
              onClick={zoomIn}
              aria-label={t('reader.zoomIn')}
            >
              <Icon name="zoom-in" size={18} />
            </button>
            <button
              type="button"
              className="reader-control"
              onClick={toggleFullscreen}
              aria-label={isFullscreen ? t('reader.exitFullscreen') : t('reader.fullscreen')}
            >
              <Icon name="fullscreen" size={18} />
            </button>
          </div>
        </div>
      </div>

      <div className="reader-bottom">
        <div className={`reader-thumb-drawer${showThumbnails ? ' is-open' : ''}`}>
          <button
            type="button"
            className="reader-thumb-handle"
            aria-expanded={showThumbnails}
            aria-controls="reader-thumbnails"
            aria-label={
              showThumbnails ? t('reader.hideThumbnails') : t('reader.showThumbnails')
            }
            title={
              showThumbnails ? t('reader.hideThumbnails') : t('reader.showThumbnails')
            }
            onClick={() => setShowThumbnails((visible) => !visible)}
          >
            <Icon name={showThumbnails ? 'chevron-up' : 'chevron-down'} size={15} />
          </button>
          <div
            id="reader-thumbnails"
            className="reader-thumb-drawer-body"
            aria-hidden={!showThumbnails}
          >
            <div className="reader-thumbs" aria-label={t('reader.thumbnails')}>
              {canvases.map((item, thumbIndex) => {
                const thumb =
                  item.local_thumbnail_url ??
                  item.thumbnail_url ??
                  item.local_url ??
                  item.image_url;
                return (
                  <button
                    key={item.id}
                    type="button"
                    ref={(element) => {
                      thumbRefs.current[thumbIndex] = element;
                    }}
                    className={
                      thumbIndex === index ? 'reader-thumb is-active' : 'reader-thumb'
                    }
                    onClick={() => goTo(thumbIndex)}
                    aria-current={thumbIndex === index ? 'page' : undefined}
                    aria-label={t('reader.pageLabel', {
                      index: thumbIndex + 1,
                      label: pageLabel(item.label, thumbIndex + 1, t),
                    })}
                  >
                    {thumb ? (
                      <img
                        src={thumb}
                        alt=""
                        loading="lazy"
                        referrerPolicy="no-referrer"
                      />
                    ) : (
                      <span>{thumbIndex + 1}</span>
                    )}
                    {item.local_available ? (
                      <i className="thumb-local" aria-label={t('reader.localCopy')} />
                    ) : null}
                  </button>
                );
              })}
            </div>
          </div>
        </div>

        <div className="reader-footer">
          <span>
            {hasSourceLabel
              ? t('reader.pageFooter', { page: index + 1, label: currentLabel })
              : t('reader.pageFooterPlain', { page: index + 1 })}
          </span>
          <span>
            {localSrc ? t('reader.localCopy') : t('reader.remoteSource')} · {meta.label}
          </span>
          <span className="keyboard-hint">{t('reader.keyboardHint')}</span>
          <Link to="/" className="reader-return">
            {t('reader.library')}
          </Link>
          <button
            type="button"
            className="reader-return"
            onClick={() => navigate(`/books/${book.id}`)}
          >
            {t('reader.returnBook')}
          </button>
        </div>
      </div>
    </div>
  );
}
