import { api } from '../api';
import { Callout, ErrorPanel, LoadingBlock, ProgressBar } from '../components/Feedback';
import { Icon } from '../components/Icon';
import { useAsync, useDocumentTitle } from '../hooks';
import { formatBytes } from '../lib';
import { useErrorMessage, useI18n } from '../i18n';

export function SettingsPage() {
  const { t } = useI18n();
  const errorMessage = useErrorMessage();
  useDocumentTitle(t('settings.title'));
  const { data, loading, error, reload } = useAsync(
    async () => {
      const [storage, info, health] = await Promise.all([
        api.storage(),
        api.systemInfo(),
        api.health(),
      ]);
      return { storage, info, health };
    },
    'settings',
  );

  return (
    <div className="page settings-page">
      <div className="container container-narrow">
        <header className="page-heading">
          <div>
            <p className="eyebrow">{t('settings.eyebrow')}</p>
            <h1>{t('settings.title')}</h1>
            <p className="lede">{t('settings.lede')}</p>
          </div>
          <button type="button" className="button button-secondary" onClick={reload}>
            <Icon name="refresh" size={16} />
            {t('settings.refresh')}
          </button>
        </header>

        {error && !data ? (
          <ErrorPanel
            title={t('settings.errorTitle')}
            message={errorMessage(error)}
            onRetry={reload}
          />
        ) : null}
        {loading && !data ? <LoadingBlock label={t('settings.loading')} /> : null}

        {data ? (
          <>
            <section className="panel">
              <div className="section-heading">
                <div>
                  <p className="eyebrow">{t('settings.storageEyebrow')}</p>
                  <h2>{t('settings.storageTitle')}</h2>
                </div>
                <span
                  className={`health-pill health-${data.health.database === 'ok' ? 'ok' : 'bad'}`}
                >
                  <span />
                  {data.health.database === 'ok'
                    ? t('settings.healthy')
                    : t('settings.databaseIssue')}
                </span>
              </div>
              <div className="storage-grid">
                <div className="storage-stat">
                  <span>{t('settings.bookFiles')}</span>
                  <strong>{formatBytes(data.storage.books_bytes)}</strong>
                  <small>
                    {t('settings.bookFilesMeta', {
                      books: data.storage.book_count,
                      files: data.storage.book_file_count,
                    })}
                  </small>
                </div>
                <div className="storage-stat">
                  <span>{t('settings.database')}</span>
                  <strong>{formatBytes(data.storage.database_bytes)}</strong>
                  <small>{t('settings.databaseMeta')}</small>
                </div>
                <div className="storage-stat">
                  <span>{t('settings.free')}</span>
                  <strong>{formatBytes(data.storage.free_bytes)}</strong>
                  <small>
                    {t('settings.freeMeta', {
                      total: formatBytes(data.storage.total_bytes),
                    })}
                  </small>
                </div>
              </div>
              <ProgressBar
                value={
                  data.storage.total_bytes
                    ? (data.storage.books_bytes / data.storage.total_bytes) * 100
                    : 0
                }
                label={t('settings.storageShare')}
              />
              <p className="muted small">
                {t('settings.storageCopy')
                  .split(/(\/books|\/data)/g)
                  .map((part, index) =>
                    part === '/books' || part === '/data' ? (
                      <code key={`${part}-${index}`}>{part}</code>
                    ) : (
                      part
                    ),
                  )}
              </p>
            </section>

            <section className="panel">
              <div className="section-heading">
                <div>
                  <p className="eyebrow">{t('settings.runtimeEyebrow')}</p>
                  <h2>{t('settings.runtimeTitle')}</h2>
                </div>
              </div>
              <dl className="settings-table">
                <div>
                  <dt>{t('settings.version')}</dt>
                  <dd>{data.info.version}</dd>
                </div>
                <div>
                  <dt>{t('settings.environment')}</dt>
                  <dd>{data.info.environment}</dd>
                </div>
                <div>
                  <dt>{t('settings.concurrency')}</dt>
                  <dd>{data.info.download_concurrency}</dd>
                </div>
                <div>
                  <dt>{t('settings.maxWidth')}</dt>
                  <dd>
                    {data.info.download_max_width > 0
                      ? `${data.info.download_max_width} px`
                      : t('settings.noWidthCeiling')}{' '}
                    ({data.info.download_image_format})
                  </dd>
                </div>
                <div>
                  <dt>{t('settings.coverWidth')}</dt>
                  <dd>{data.info.cover_max_width} px</dd>
                </div>
                <div>
                  <dt>{t('settings.manifestLimit')}</dt>
                  <dd>{formatBytes(data.info.max_manifest_bytes)}</dd>
                </div>
                <div>
                  <dt>{t('settings.imageLimit')}</dt>
                  <dd>{formatBytes(data.info.max_image_bytes)}</dd>
                </div>
                <div>
                  <dt>{t('settings.autoResume')}</dt>
                  <dd>
                    {data.info.auto_resume_downloads
                      ? t('settings.autoResumeOn')
                      : t('settings.autoResumeOff')}
                  </dd>
                </div>
                <div>
                  <dt>{t('settings.activeDownloads')}</dt>
                  <dd>{data.health.active_downloads}</dd>
                </div>
              </dl>
              <Callout tone="info">{t('settings.downloadNote')}</Callout>
            </section>

            <section className="panel">
              <div className="section-heading">
                <div>
                  <p className="eyebrow">{t('settings.securityEyebrow')}</p>
                  <h2>{t('settings.securityTitle')}</h2>
                </div>
              </div>
              <p>{t('settings.securityNotice')}</p>
              <dl className="settings-table">
                <div>
                  <dt>{t('settings.privateHosts')}</dt>
                  <dd>
                    {t('settings.privateHostsValue', {
                      count: data.info.allowed_private_host_count,
                    })}
                  </dd>
                </div>
                <div>
                  <dt>{t('settings.privateAllowed')}</dt>
                  <dd>
                    {data.info.allow_private_networks
                      ? t('settings.privateAllowedYes')
                      : t('settings.privateAllowedNo')}
                  </dd>
                </div>
              </dl>
              {data.info.allow_private_networks ? (
                <Callout tone="warning" title={t('settings.devWarningTitle')}>
                  <code>MANNAZIA_ALLOW_PRIVATE_NETWORKS=true</code>
                  {t('settings.devWarningCopy')}
                </Callout>
              ) : null}
              <p className="muted small">{t('settings.rightsNote')}</p>
            </section>

            <section className="panel">
              <div className="section-heading">
                <div>
                  <p className="eyebrow">{t('settings.operationsEyebrow')}</p>
                  <h2>{t('settings.operationsTitle')}</h2>
                </div>
              </div>
              <p>
                {t('settings.backupCopy')
                  .split(/(\/data|\/books)/g)
                  .map((part, index) =>
                    part === '/data' || part === '/books' ? (
                      <code key={`${part}-${index}`}>{part}</code>
                    ) : (
                      part
                    ),
                  )}
              </p>
              <pre className="code-block">
                <code>{`sqlite3 /data/mannazia.db ".backup '/backup/mannazia.db'"
tar -czf /backup/mannazia-books-$(date +%F).tar.gz -C / books`}</code>
              </pre>
              <p className="muted small">
                {t('settings.backupNote')
                  .split(/(\/data|\/books)/g)
                  .map((part, index) =>
                    part === '/data' || part === '/books' ? (
                      <code key={`${part}-${index}`}>{part}</code>
                    ) : (
                      part
                    ),
                  )}
              </p>
              <p>
                <a className="button button-secondary" href="/api/docs">
                  <Icon name="external" size={15} />
                  {t('settings.apiDocs')}
                </a>
              </p>
            </section>
          </>
        ) : null}
      </div>
    </div>
  );
}
