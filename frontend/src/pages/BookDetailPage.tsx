import { Link, useNavigate, useParams } from 'react-router-dom';
import { useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { api } from '../api';
import { Cover } from '../components/Cover';
import { StateBadge } from '../components/StateBadge';
import { ConfirmButton } from '../components/ConfirmButton';
import {
  Badge,
  Callout,
  ErrorPanel,
  LoadingBlock,
  ProgressBar,
} from '../components/Feedback';
import { Icon } from '../components/Icon';
import { useAsync, useDocumentTitle } from '../hooks';
import {
  bookProgressPercent,
  bookStateMeta,
  formatBytes,
  formatDate,
  formatDateTime,
  jobStateMeta,
  localizeDiagnostic,
  parseTagInput,
  safeHttpUrl,
} from '../lib';
import { useErrorMessage, useI18n } from '../i18n';
import type { BookDetail, DownloadQuality } from '../types';

interface EditDraft {
  title: string;
  creator: string;
  description: string;
  language: string;
  date: string;
  rights: string;
  rights_uri: string;
  tags: string;
}

function editDraft(book: BookDetail): EditDraft {
  return {
    title: book.title,
    creator: book.creator ?? '',
    description: book.description ?? '',
    language: book.language ?? '',
    date: book.date ?? '',
    rights: book.rights ?? '',
    rights_uri: book.rights_uri ?? '',
    tags: book.tags.join(', '),
  };
}

export function BookDetailPage() {
  const { t, language, locale } = useI18n();
  const errorMessage = useErrorMessage();
  const { bookId = '' } = useParams();
  const navigate = useNavigate();
  const [busy, setBusy] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [editing, setEditing] = useState<EditDraft | null>(null);
  const [downloadMenuOpen, setDownloadMenuOpen] = useState(false);
  const downloadMenuRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!downloadMenuOpen) return;
    const onPointerDown = (event: PointerEvent) => {
      const target = event.target as Node | null;
      if (target && !downloadMenuRef.current?.contains(target)) {
        setDownloadMenuOpen(false);
      }
    };
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setDownloadMenuOpen(false);
    };
    document.addEventListener('pointerdown', onPointerDown);
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('pointerdown', onPointerDown);
      document.removeEventListener('keydown', onKey);
    };
  }, [downloadMenuOpen]);

  useEffect(() => {
    if (!editing) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setEditing(null);
    };
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    document.addEventListener('keydown', onKey);
    return () => {
      document.body.style.overflow = previousOverflow;
      document.removeEventListener('keydown', onKey);
    };
  }, [editing]);

  const { data, loading, error, reload } = useAsync(
    () => api.getBook(bookId),
    bookId,
    { pollMs: 0 },
  );

  const book = data ?? null;
  useDocumentTitle(book?.title ?? t('reader.book'));
  const activeJobId = book?.active_job?.id ?? null;

  useEffect(() => {
    if (!activeJobId) return;
    const timer = window.setInterval(() => void reload(), 2000);
    return () => window.clearInterval(timer);
  }, [activeJobId, reload]);

  const run = async (name: string, action: () => Promise<unknown>) => {
    setBusy(name);
    setActionError(null);
    try {
      await action();
      await reload();
    } catch (requestError) {
      setActionError(errorMessage(requestError));
    } finally {
      setBusy(null);
    }
  };

  if (loading && !book) {
    return (
      <div className="page">
        <div className="container">
          <LoadingBlock label={t('book.loading')} />
        </div>
      </div>
    );
  }

  if (error || !book) {
    return (
      <div className="page">
        <div className="container container-narrow">
          <ErrorPanel
            title={t('book.errorTitle')}
            message={error ? errorMessage(error) : t('book.notFound')}
            onRetry={reload}
          />
          <Link className="button button-secondary" to="/">
            <Icon name="arrow-left" size={16} />
            {t('book.returnLibrary')}
          </Link>
        </div>
      </div>
    );
  }

  const meta = bookStateMeta(book.download_state, t);
  const job = book.active_job ?? book.latest_job;
  const jobMeta = job ? jobStateMeta(job.state, t) : null;
  const qualityOptions: Array<{
    value: DownloadQuality;
    label: string;
    description: string;
  }> = [
    {
      value: 'reading',
      label: t('book.quality.reading.label'),
      description: t('book.quality.reading.description'),
    },
    {
      value: 'standard',
      label: t('book.quality.standard.label'),
      description: t('book.quality.standard.description'),
    },
    {
      value: 'appreciation',
      label: t('book.quality.appreciation.label'),
      description: t('book.quality.appreciation.description'),
    },
    {
      value: 'research',
      label: t('book.quality.research.label'),
      description: t('book.quality.research.description'),
    },
  ];
  const qualityLabel = (quality: string) =>
    qualityOptions.find((option) => option.value === quality)?.label ??
    t('book.quality.legacy');
  const hasLocalPages = book.completed_pages > 0;
  const canStart =
    !book.active_job &&
    book.failed_pages === 0 &&
    book.completed_pages < book.total_pages &&
    book.download_state !== 'offline';
  const showLocalCopyPanel = Boolean(
    book.active_job ||
      book.latest_job ||
      book.completed_pages > 0 ||
      book.failed_pages > 0,
  );
  const jobPercent = job
    ? bookProgressPercent(job.completed_pages, job.total_pages)
    : bookProgressPercent(book.completed_pages, book.total_pages);
  const unsupportedNote =
    book.unsupported_canvases > 0
      ? t('book.unsupportedNote', { count: book.unsupported_canvases })
      : null;
  const coverWarning = book.warnings.find((warning) =>
    warning.startsWith('Cover image') ||
    warning.startsWith('No cover page') ||
    warning.startsWith('The selected cover page'),
  );

  const startJob = (name: string, action: (jobId: string) => Promise<unknown>) => {
    if (!job) return;
    void run(name, () => action(job.id));
  };

  const handleSave = async () => {
    if (!editing) return;
    setBusy('save');
    setActionError(null);
    try {
      await api.updateBook(book.id, {
        title: editing.title,
        creator: editing.creator,
        description: editing.description,
        language: editing.language,
        date: editing.date,
        rights: editing.rights,
        rights_uri: editing.rights_uri,
        tags: parseTagInput(editing.tags),
      });
      setEditing(null);
      await reload();
    } catch (requestError) {
      setActionError(errorMessage(requestError));
    } finally {
      setBusy(null);
    }
  };

  const renderingLinks = [...book.rendering, ...book.see_also].filter(
    (item) => item.id && /^https?:/i.test(item.id),
  );
  const rightsText = book.rights || book.required_statement.value;

  return (
    <div className="page book-page">
      <div className="container">
        <nav className="breadcrumb" aria-label={t('book.breadcrumbLibrary')}>
          <Link to="/">
            <Icon name="arrow-left" size={15} />
            {t('book.breadcrumbLibrary')}
          </Link>
          <span aria-hidden="true">/</span>
          <span>{book.title}</span>
        </nav>

        <header className="book-hero">
          <div className="book-hero-cover">
            <Cover
              title={book.title}
              localUrl={book.local_cover_url}
              remoteUrl={book.thumbnail_url}
            />
            <div className="cover-state">
              <StateBadge state={book.download_state} />
            </div>
          </div>
          <div className="book-hero-main">
            <div className="hero-topline">
              <span className="eyebrow">
                {t('book.apiVersion', { version: book.api_version })}
              </span>
              {book.language ? <Badge>{book.language}</Badge> : null}
            </div>
            <h1>{book.title}</h1>
            <p className="book-byline">{book.creator || t('book.creatorUnknown')}</p>
            <p className="book-description">
              {book.summary || t('book.noDescription')}
            </p>

            <div className="hero-actions">
              <Link
                className="button button-primary button-large"
                to={`/books/${book.id}/read?page=${Math.min(
                  book.last_read_index + 1,
                  Math.max(1, book.total_canvases),
                )}`}
              >
                <Icon name="library" size={18} />
                {book.last_read_index > 0
                  ? t('book.continue', { page: book.last_read_index + 1 })
                  : t('book.read')}
              </Link>
              {canStart ? (
                <div className="download-choice" ref={downloadMenuRef}>
                  <button
                    type="button"
                    className="button button-secondary button-large"
                    disabled={busy !== null}
                    aria-haspopup="menu"
                    aria-expanded={downloadMenuOpen}
                    onClick={() => setDownloadMenuOpen((open) => !open)}
                  >
                    <Icon name="download" size={18} />
                    {hasLocalPages ? t('book.downloadRemaining') : t('book.downloadToNas')}
                    <Icon name="chevron-down" size={15} />
                  </button>
                  {downloadMenuOpen ? (
                    <div
                      className="download-menu"
                      role="menu"
                      aria-label={t('book.downloadQualityTitle')}
                    >
                      <p className="download-menu-title">
                        {t('book.downloadQualityTitle')}
                      </p>
                      {qualityOptions.map((option) => (
                        <button
                          key={option.value}
                          type="button"
                          className="download-menu-item"
                          role="menuitem"
                          onClick={() => {
                            setDownloadMenuOpen(false);
                            void run('start', () =>
                              api.startDownload(book.id, option.value),
                            );
                          }}
                        >
                          <span className="download-menu-label">{option.label}</span>
                          <span className="download-menu-description">
                            {option.description}
                          </span>
                        </button>
                      ))}
                      <p className="download-menu-note">{t('book.quality.note')}</p>
                    </div>
                  ) : null}
                </div>
              ) : null}
              <button
                type="button"
                className="button button-ghost"
                onClick={() => setEditing(editDraft(book))}
              >
                {t('book.editRecord')}
              </button>
            </div>

            <dl className="hero-facts">
              <div>
                <dt>{t('book.pages')}</dt>
                <dd>{book.total_canvases}</dd>
              </div>
              <div>
                <dt>{t('book.localPages')}</dt>
                <dd>
                  {book.completed_pages}
                  {book.total_pages ? ` / ${book.total_pages}` : ''}
                </dd>
              </div>
              <div>
                <dt>{t('book.added')}</dt>
                <dd>{formatDate(book.imported_at, locale)}</dd>
              </div>
              <div>
                <dt>{t('book.rights')}</dt>
                <dd>
                  {book.rights_uri && safeHttpUrl(book.rights_uri) ? (
                    <a
                      className="hero-rights-link"
                      href={safeHttpUrl(book.rights_uri)}
                      target="_blank"
                      rel="noreferrer noopener"
                    >
                      <Icon name="external" size={12} />
                      {t('book.readRights')}
                    </a>
                  ) : rightsText ? (
                    t('book.rightsSeeBelow')
                  ) : (
                    t('common.notStated')
                  )}
                </dd>
              </div>
            </dl>

            {book.tags.length ? (
              <div className="tag-list" aria-label={t('import.fieldTags')}>
                {book.tags.map((tag) => (
                  <span key={tag} className="tag">
                    {tag}
                  </span>
                ))}
              </div>
            ) : null}
          </div>
        </header>

        {coverWarning ? (
          <Callout tone="warning" title={t('book.coverWarningTitle')}>
            {t('book.coverWarningCopy')}
          </Callout>
        ) : null}

        {actionError ? (
          <Callout tone="warning" title={t('book.actionErrorTitle')}>
            {actionError}
          </Callout>
        ) : null}

        <div className="book-columns">
          <div className="book-main-column">
            {showLocalCopyPanel ? (
              <section className="panel local-copy-panel">
                <div className="panel-heading">
                  <div>
                    <p className="eyebrow">{t('book.localCopyEyebrow')}</p>
                    <h2>{t('book.localCopyTitle')}</h2>
                  </div>
                  <StateBadge state={book.download_state} />
                </div>
                <p className="state-description">{meta.description}</p>

                {job ? (
                  <div className="job-block">
                    <div className="job-block-head">
                      <div>
                        <strong>{jobMeta?.label ?? job.state}</strong>
                        <span className="muted">
                          {' '}
                          ·{' '}
                          {t('book.completedOf', {
                            completed: job.completed_pages,
                            total: job.total_pages || '—',
                          })}
                        </span>
                      </div>
                      {job.state === 'downloading' || job.state === 'queued' ? (
                        <span
                          className="live-indicator"
                          aria-label={t('state.downloading.label')}
                        >
                          <span />
                          {t('book.live')}
                        </span>
                      ) : null}
                    </div>
                    <ProgressBar
                      value={jobPercent}
                      label={t('book.downloadedBytes', {
                        size: formatBytes(job.bytes_downloaded),
                      })}
                      tone={job.state === 'completed' ? 'green' : 'gold'}
                    />
                    <div className="job-stats">
                      <span>
                        <strong>{job.completed_pages}</strong> {t('book.completeLabel')}
                      </span>
                      <span>
                        <strong>{job.failed_pages}</strong> {t('book.failedLabel')}
                      </span>
                      <span>
                        {t('book.qualityLabel', { quality: qualityLabel(job.quality) })}
                      </span>
                      <span>
                        <strong>{formatBytes(book.local_storage_bytes)}</strong>{' '}
                        {book.archive_bytes > 0
                          ? t('book.cbzStorage')
                          : t('book.onDiskLabel')}
                      </span>
                      <span>
                        {t('book.updated', { date: formatDateTime(job.updated_at, locale) })}
                      </span>
                    </div>
                    {job.error ? (
                      <Callout tone={job.state === 'cancelled' ? 'info' : 'warning'}>
                        {localizeDiagnostic(job.error, t, language)}
                      </Callout>
                    ) : null}
                    <div className="button-row">
                      {job.state === 'queued' || job.state === 'downloading' ? (
                        <>
                          <button
                            type="button"
                            className="button button-secondary"
                            disabled={busy !== null}
                            onClick={() =>
                              startJob('pause', (id) => api.pauseDownload(id))
                            }
                          >
                            <Icon name="pause" size={16} />
                            {t('book.pause')}
                          </button>
                          <ConfirmButton
                            label={t('book.cancelDownload')}
                            confirmLabel={t('book.confirmCancel')}
                            onConfirm={() =>
                              startJob('cancel', (id) => api.cancelDownload(id))
                            }
                            busy={busy === 'cancel'}
                          />
                        </>
                      ) : null}
                      {job.state === 'paused' ? (
                        <>
                          <button
                            type="button"
                            className="button button-primary"
                            disabled={busy !== null}
                            onClick={() =>
                              startJob('resume', (id) => api.resumeDownload(id))
                            }
                          >
                            <Icon name="play" size={16} />
                            {t('book.resume')}
                          </button>
                          <ConfirmButton
                            label={t('book.cancelDownload')}
                            confirmLabel={t('book.confirmCancel')}
                            onConfirm={() =>
                              startJob('cancel', (id) => api.cancelDownload(id))
                            }
                            busy={busy === 'cancel'}
                          />
                        </>
                      ) : null}
                      {job.state === 'failed' || job.state === 'cancelled' ? (
                        <button
                          type="button"
                          className="button button-secondary"
                          disabled={busy !== null}
                          onClick={() => startJob('retry', (id) => api.retryDownload(id))}
                        >
                          <Icon name="refresh" size={16} />
                          {t('book.retryFailed')}
                        </button>
                      ) : null}
                      {hasLocalPages &&
                      job.state !== 'queued' &&
                      job.state !== 'downloading' ? (
                        <ConfirmButton
                          label={t('book.removeLocal')}
                          confirmLabel={t('book.confirmRemoveLocal')}
                          busy={busy === 'delete-local'}
                          onConfirm={() =>
                            void run('delete-local', () => api.deleteLocalCopy(book.id))
                          }
                        />
                      ) : null}
                    </div>
                  </div>
                ) : (
                  <div className="empty-local">
                    <p>{t('book.noLocalCopy')}</p>
                  </div>
                )}

                {unsupportedNote ? <Callout tone="info">{unsupportedNote}</Callout> : null}
                {book.failed_pages > 0 ? (
                  <Callout tone="warning">
                    {t('book.failedPagesNote', { count: book.failed_pages })}
                  </Callout>
                ) : null}
              </section>
            ) : null}

            <section className="panel">
              <div className="section-heading">
                <div>
                  <p className="eyebrow">{t('book.metadataEyebrow')}</p>
                  <h2>{t('book.metadataTitle')}</h2>
                </div>
                <button
                  type="button"
                  className="button button-ghost"
                  onClick={() => setEditing(editDraft(book))}
                >
                  {t('common.edit')}
                </button>
              </div>
              <dl className="metadata-table">
                {book.metadata.map((entry, index) => (
                  <div key={`${entry.label}-${index}`}>
                    <dt>{entry.label || t('book.note')}</dt>
                    <dd>{entry.value}</dd>
                  </div>
                ))}
                <div>
                  <dt>{t('book.sourceManifest')}</dt>
                  <dd>
                    <a
                      href={book.manifest_url}
                      target="_blank"
                      rel="noreferrer noopener"
                      className="source-link"
                    >
                      <Icon name="external" size={13} />
                      {book.manifest_url}
                    </a>
                  </dd>
                </div>
                {book.provider ? (
                  <div>
                    <dt>{t('book.provider')}</dt>
                    <dd>{book.provider}</dd>
                  </div>
                ) : null}
                {book.required_statement.value ? (
                  <div>
                    <dt>
                      {book.required_statement.label || t('book.attribution')}
                    </dt>
                    <dd>{book.required_statement.value}</dd>
                  </div>
                ) : null}
              </dl>
            </section>

            {book.structures.length ? (
              <section className="panel">
                <div className="section-heading">
                  <div>
                    <p className="eyebrow">{t('book.structuresEyebrow')}</p>
                    <h2>{t('book.contents')}</h2>
                  </div>
                </div>
                <ul className="structures">
                  {book.structures.map((node, index) => (
                    <li
                      key={node.id ?? `${node.label}-${index}`}
                      style={{ paddingLeft: `${Math.min(node.depth, 4) * 1.2}rem` }}
                    >
                      <span>{node.label || t('book.untitledSection')}</span>
                      {node.canvas_ids.length ? (
                        <span className="muted">
                          {' '}
                          · {t('book.structurePages', { count: node.canvas_ids.length })}
                        </span>
                      ) : null}
                    </li>
                  ))}
                </ul>
              </section>
            ) : null}

            {book.warnings.length ? (
              <section className="panel">
                <div className="section-heading">
                  <div>
                    <p className="eyebrow">{t('book.notesEyebrow')}</p>
                    <h2>{t('book.warningsTitle')}</h2>
                  </div>
                </div>
                <ul className="warning-list">
                  {book.warnings.map((warning) => (
                    <li key={warning}>{localizeDiagnostic(warning, t, language)}</li>
                  ))}
                </ul>
              </section>
            ) : null}
          </div>

          <aside className="book-side-column">
            {renderingLinks.length ? (
              <section className="panel">
                <p className="eyebrow">{t('book.renderingsEyebrow')}</p>
                <h2>{t('book.renderingsTitle')}</h2>
                <ul className="link-list">
                  {renderingLinks.map((link) => (
                    <li key={link.id}>
                      <a href={link.id ?? '#'} target="_blank" rel="noreferrer noopener">
                        {link.label || link.format || t('book.openResource')}
                        <Icon name="external" size={13} />
                      </a>
                    </li>
                  ))}
                </ul>
              </section>
            ) : null}

            <section className="panel danger-panel">
              <p className="eyebrow">{t('book.manageEyebrow')}</p>
              <h2>{t('book.removeTitle')}</h2>
              <p className="muted">{t('book.removeCopy')}</p>
              <ConfirmButton
                className="button button-danger"
                label={t('book.deleteBook')}
                confirmLabel={t('book.confirmDelete')}
                busy={busy === 'delete-book'}
                onConfirm={() =>
                  void run('delete-book', async () => {
                    await api.deleteBook(book.id);
                    navigate('/');
                  })
                }
              />
            </section>
          </aside>
        </div>
      </div>

      {editing
        ? createPortal(
            <div
              className="modal-backdrop"
              role="presentation"
              onMouseDown={() => setEditing(null)}
            >
          <div
            className="modal"
            role="dialog"
            aria-modal="true"
            aria-labelledby="edit-record-title"
            onMouseDown={(event) => event.stopPropagation()}
          >
            <div className="modal-heading">
              <div>
                <p className="eyebrow">{t('book.editEyebrow')}</p>
                <h2 id="edit-record-title">{t('book.editTitle')}</h2>
              </div>
              <button
                type="button"
                className="icon-button"
                onClick={() => setEditing(null)}
                aria-label={t('common.close')}
              >
                <Icon name="x" size={18} />
              </button>
            </div>
            <div className="form-grid">
              <div className="field">
                <label htmlFor="edit-title">{t('import.fieldTitle')}</label>
                <input
                  id="edit-title"
                  autoFocus
                  value={editing.title}
                  onChange={(event) =>
                    setEditing({ ...editing, title: event.target.value })
                  }
                />
              </div>
              <div className="field">
                <label htmlFor="edit-creator">{t('import.fieldCreator')}</label>
                <input
                  id="edit-creator"
                  value={editing.creator}
                  onChange={(event) =>
                    setEditing({ ...editing, creator: event.target.value })
                  }
                />
              </div>
              <div className="field">
                <label htmlFor="edit-language">{t('import.fieldLanguage')}</label>
                <input
                  id="edit-language"
                  value={editing.language}
                  onChange={(event) =>
                    setEditing({ ...editing, language: event.target.value })
                  }
                />
              </div>
              <div className="field">
                <label htmlFor="edit-date">{t('import.fieldDate')}</label>
                <input
                  id="edit-date"
                  value={editing.date}
                  onChange={(event) => setEditing({ ...editing, date: event.target.value })}
                />
              </div>
              <div className="field field-wide">
                <label htmlFor="edit-description">{t('import.fieldDescription')}</label>
                <textarea
                  id="edit-description"
                  rows={3}
                  value={editing.description}
                  onChange={(event) =>
                    setEditing({ ...editing, description: event.target.value })
                  }
                />
              </div>
              <div className="field field-wide">
                <label htmlFor="edit-rights">{t('import.fieldRights')}</label>
                <textarea
                  id="edit-rights"
                  rows={2}
                  value={editing.rights}
                  onChange={(event) =>
                    setEditing({ ...editing, rights: event.target.value })
                  }
                />
              </div>
              <div className="field">
                <label htmlFor="edit-rights-uri">{t('import.fieldRightsUri')}</label>
                <input
                  id="edit-rights-uri"
                  value={editing.rights_uri}
                  onChange={(event) =>
                    setEditing({ ...editing, rights_uri: event.target.value })
                  }
                />
              </div>
              <div className="field">
                <label htmlFor="edit-tags">{t('import.fieldTags')}</label>
                <input
                  id="edit-tags"
                  value={editing.tags}
                  onChange={(event) => setEditing({ ...editing, tags: event.target.value })}
                />
              </div>
            </div>
            <div className="modal-actions">
              <button
                type="button"
                className="button button-primary"
                onClick={() => void handleSave()}
                disabled={busy === 'save'}
              >
                {busy === 'save' ? t('common.saving') : t('book.saveRecord')}
              </button>
              <button
                type="button"
                className="button button-ghost"
                onClick={() => setEditing(null)}
              >
                {t('common.cancel')}
              </button>
            </div>
          </div>
        </div>,
        document.body,
      )
      : null}
    </div>
  );
}
