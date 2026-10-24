import { Link } from 'react-router-dom';
import { useState } from 'react';
import { api } from '../api';
import { ConfirmButton } from '../components/ConfirmButton';
import { EmptyState, ErrorPanel, LoadingBlock, ProgressBar } from '../components/Feedback';
import { Icon } from '../components/Icon';
import { StateBadge } from '../components/StateBadge';
import { useAsync, useDocumentTitle } from '../hooks';
import { formatBytes, formatDateTime, jobStateMeta, localizeDiagnostic } from '../lib';
import { useErrorMessage, useI18n } from '../i18n';
import type { DownloadJob } from '../types';

export function DownloadsPage() {
  const { t, language, locale } = useI18n();
  const errorMessage = useErrorMessage();
  useDocumentTitle(t('downloads.title'));
  const [busy, setBusy] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const { data, loading, error, reload } = useAsync(
    () => api.listDownloads({ limit: 100 }),
    'downloads',
    { pollMs: 2000 },
  );
  const storage = useAsync(() => api.storage(), 'downloads-storage');
  const jobs = data?.items ?? [];
  const active = jobs.filter((job) =>
    ['queued', 'downloading'].includes(job.state),
  ).length;

  const run = async (name: string, action: () => Promise<unknown>) => {
    setBusy(name);
    setActionError(null);
    try {
      await action();
      await Promise.all([reload(), storage.reload()]);
    } catch (requestError) {
      setActionError(errorMessage(requestError));
    } finally {
      setBusy(null);
    }
  };

  const actions = (job: DownloadJob) => {
    if (job.state === 'queued' || job.state === 'downloading') {
      return (
        <>
          <button
            type="button"
            className="button button-secondary"
            disabled={busy !== null}
            onClick={() => void run(`pause-${job.id}`, () => api.pauseDownload(job.id))}
          >
            <Icon name="pause" size={16} />
            {t('downloads.pause')}
          </button>
          <ConfirmButton
            label={t('downloads.cancel')}
            confirmLabel={t('downloads.confirmCancel')}
            busy={busy === `cancel-${job.id}`}
            onConfirm={() =>
              void run(`cancel-${job.id}`, () => api.cancelDownload(job.id))
            }
          />
        </>
      );
    }
    if (job.state === 'paused') {
      return (
        <>
          <button
            type="button"
            className="button button-primary"
            disabled={busy !== null}
            onClick={() => void run(`resume-${job.id}`, () => api.resumeDownload(job.id))}
          >
            <Icon name="play" size={16} />
            {t('downloads.resume')}
          </button>
          <ConfirmButton
            label={t('downloads.cancel')}
            confirmLabel={t('downloads.confirmCancel')}
            busy={busy === `cancel-${job.id}`}
            onConfirm={() =>
              void run(`cancel-${job.id}`, () => api.cancelDownload(job.id))
            }
          />
        </>
      );
    }
    if (job.state === 'failed' || job.state === 'cancelled') {
      return (
        <button
          type="button"
          className="button button-secondary"
          disabled={busy !== null}
          onClick={() => void run(`retry-${job.id}`, () => api.retryDownload(job.id))}
        >
          <Icon name="refresh" size={16} />
          {t('downloads.retry')}
        </button>
      );
    }
    return (
      <Link className="button button-secondary" to={`/books/${job.book_id}`}>
        {t('downloads.openBook')}
      </Link>
    );
  };

  return (
    <div className="page downloads-page">
      <div className="container">
        <header className="page-heading">
          <div>
            <p className="eyebrow">{t('downloads.eyebrow')}</p>
            <h1>{t('downloads.title')}</h1>
            <p className="lede">{t('downloads.lede')}</p>
          </div>
          <button
            type="button"
            className="button button-secondary"
            onClick={() => {
              void reload();
              void storage.reload();
            }}
          >
            <Icon name="refresh" size={16} />
            {t('downloads.refresh')}
          </button>
        </header>

        <div className="download-summary">
          <div className="summary-card">
            <span className="summary-label">{t('downloads.active')}</span>
            <strong>{active}</strong>
          </div>
          <div className="summary-card">
            <span className="summary-label">{t('downloads.stored')}</span>
            <strong>{formatBytes(storage.data?.books_bytes ?? 0)}</strong>
          </div>
          <div className="summary-card">
            <span className="summary-label">{t('downloads.free')}</span>
            <strong>{formatBytes(storage.data?.free_bytes ?? 0)}</strong>
          </div>
          <div className="summary-card">
            <span className="summary-label">{t('downloads.jobs')}</span>
            <strong>{data?.total ?? 0}</strong>
          </div>
        </div>

        {actionError ? (
          <ErrorPanel title={t('downloads.actionFailed')} message={actionError} />
        ) : null}
        {error && !data ? (
          <ErrorPanel
            title={t('downloads.errorTitle')}
            message={errorMessage(error)}
            onRetry={reload}
          />
        ) : null}
        {loading && !data ? <LoadingBlock label={t('downloads.loading')} /> : null}

        {data && jobs.length === 0 ? (
          <EmptyState
            title={t('downloads.emptyTitle')}
            icon="download"
            action={
              <Link className="button button-secondary" to="/">
                {t('downloads.browse')}
              </Link>
            }
          >
            <p>{t('downloads.emptyCopy')}</p>
          </EmptyState>
        ) : null}

        {jobs.length ? (
          <div className="download-list">
            {jobs.map((job) => {
              const meta = jobStateMeta(job.state, t);
              return (
                <article className="download-row" key={job.id}>
                  <div className="download-row-main">
                    <div className="download-row-heading">
                      <div>
                        <Link to={`/books/${job.book_id}`} className="download-title">
                          {job.book_title || t('downloads.untitledBook')}
                        </Link>
                        <p className="muted">
                          {t('downloads.job', { id: job.id.slice(0, 8) })} ·{' '}
                          {meta.description}
                        </p>
                      </div>
                      <StateBadge state={job.state} kind="job" />
                    </div>
                    <ProgressBar
                      value={job.progress_percent}
                      label={t('downloads.progress', {
                        completed: job.completed_pages,
                        total: job.total_pages,
                      })}
                      tone={job.state === 'completed' ? 'green' : 'gold'}
                    />
                    <div className="job-stats">
                      <span>
                        <strong>{job.completed_pages}</strong>{' '}
                        {t('downloads.completeLabel')}
                      </span>
                      <span>
                        <strong>{job.failed_pages}</strong>{' '}
                        {t('downloads.failedLabel')}
                      </span>
                      <span>
                        <strong>{formatBytes(job.bytes_downloaded)}</strong>{' '}
                        {t('downloads.writtenLabel')}
                      </span>
                      <span>
                        {t('downloads.updated', {
                          date: formatDateTime(job.updated_at, locale),
                        })}
                      </span>
                      {job.completed_at ? (
                        <span>
                          {t('downloads.finished', {
                            date: formatDateTime(job.completed_at, locale),
                          })}
                        </span>
                      ) : null}
                    </div>
                    {job.error ? (
                      <p className="job-error">
                        {localizeDiagnostic(job.error, t, language)}
                      </p>
                    ) : null}
                  </div>
                  <div className="download-row-actions">{actions(job)}</div>
                </article>
              );
            })}
          </div>
        ) : null}
      </div>
    </div>
  );
}
