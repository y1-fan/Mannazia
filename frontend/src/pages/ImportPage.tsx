import { Link, useNavigate } from 'react-router-dom';
import { useState } from 'react';
import { api, ApiError } from '../api';
import { Badge, Callout, ErrorPanel } from '../components/Feedback';
import { Cover } from '../components/Cover';
import { Icon } from '../components/Icon';
import { useDocumentTitle } from '../hooks';
import { useErrorMessage, useI18n } from '../i18n';
import type { ImportPreview } from '../types';
import { parseTagInput, localizeDiagnostic, safeHttpUrl } from '../lib';

interface Draft {
  title: string;
  creator: string;
  description: string;
  language: string;
  date: string;
  rights: string;
  rights_uri: string;
  tags: string;
}

const EMPTY_DRAFT: Draft = {
  title: '',
  creator: '',
  description: '',
  language: '',
  date: '',
  rights: '',
  rights_uri: '',
  tags: '',
};

function draftFromPreview(preview: ImportPreview): Draft {
  return {
    title: preview.title,
    creator: preview.creator,
    description: preview.description,
    language: preview.language,
    date: preview.date,
    rights: preview.rights,
    rights_uri: preview.rights_uri,
    tags: '',
  };
}

export function ImportPage() {
  const { t, language } = useI18n();
  const errorMessage = useErrorMessage();
  useDocumentTitle(t('import.title'));
  const navigate = useNavigate();
  const [manifestUrl, setManifestUrl] = useState('');
  const [preview, setPreview] = useState<ImportPreview | null>(null);
  const [draft, setDraft] = useState<Draft>(EMPTY_DRAFT);
  const [loading, setLoading] = useState(false);
  const [importing, setImporting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [duplicateId, setDuplicateId] = useState<string | null>(null);

  const stale = Boolean(preview && manifestUrl.trim() !== preview.manifest_url);

  const validateUrl = (value: string): string | null => {
    let parsed: URL;
    try {
      parsed = new URL(value);
    } catch {
      return t('import.invalidUrl');
    }
    if (!['http:', 'https:'].includes(parsed.protocol)) {
      return t('import.invalidScheme');
    }
    if (parsed.username || parsed.password) {
      return t('import.credentials');
    }
    return null;
  };

  const handlePreview = async (event?: React.FormEvent) => {
    event?.preventDefault();
    const value = manifestUrl.trim();
    const validation = validateUrl(value);
    if (validation) {
      setError(validation);
      return;
    }
    setLoading(true);
    setError(null);
    setDuplicateId(null);
    setPreview(null);
    try {
      const result = await api.preview(value);
      setPreview(result);
      setDraft(draftFromPreview(result));
      if (result.duplicate_of) setDuplicateId(result.duplicate_of);
    } catch (requestError) {
      setError(errorMessage(requestError));
    } finally {
      setLoading(false);
    }
  };

  const handleImport = async () => {
    if (!preview || preview.duplicate_of || stale) return;
    setImporting(true);
    setError(null);
    try {
      const book = await api.importBook({
        manifest_url: preview.manifest_url,
        preview_token: preview.preview_token,
        title: draft.title,
        creator: draft.creator,
        description: draft.description,
        language: draft.language,
        date: draft.date,
        rights: draft.rights,
        rights_uri: draft.rights_uri,
        tags: parseTagInput(draft.tags),
      });
      navigate(`/books/${book.id}`);
    } catch (requestError) {
      const apiError = requestError as ApiError;
      if (apiError.code === 'duplicate_book' && apiError.details?.book_id) {
        setDuplicateId(String(apiError.details.book_id));
      }
      setError(errorMessage(requestError));
    } finally {
      setImporting(false);
    }
  };

  const reset = () => {
    setPreview(null);
    setDraft(EMPTY_DRAFT);
    setError(null);
    setDuplicateId(null);
  };

  const updateDraft = (field: keyof Draft, value: string) => {
    setDraft((current) => ({ ...current, [field]: value }));
  };

  return (
    <div className="page import-page">
      <div className="container container-narrow">
        <header className="page-heading">
          <div>
            <p className="eyebrow">{t('import.eyebrow')}</p>
            <h1>{t('import.title')}</h1>
            <p className="lede">{t('import.lede')}</p>
          </div>
        </header>

        <form className="import-form card" onSubmit={handlePreview}>
          <label htmlFor="manifest-url" className="field-label">
            {t('import.urlLabel')}
          </label>
          <div className="url-row">
            <input
              id="manifest-url"
              type="url"
              inputMode="url"
              autoComplete="off"
              spellCheck={false}
              value={manifestUrl}
              onChange={(event) => setManifestUrl(event.target.value)}
              placeholder={t('import.urlPlaceholder')}
              required
            />
            <button type="submit" className="button button-secondary" disabled={loading}>
              {loading ? t('import.reading') : t('import.preview')}
            </button>
          </div>
          <p className="field-hint">{t('import.hint')}</p>
        </form>

        {error ? (
          <ErrorPanel
            title={t('import.errorTitle')}
            message={error}
            onRetry={preview ? undefined : () => void handlePreview()}
          />
        ) : null}

        {duplicateId && !preview?.duplicate_of ? (
          <Callout tone="warning" title={t('import.duplicateTitle')}>
            <Link className="button button-secondary" to={`/books/${duplicateId}`}>
              {t('import.openExisting')}
            </Link>
          </Callout>
        ) : null}

        {loading ? (
          <div className="preview-loading card" role="status">
            <span className="spinner" aria-hidden="true" />
            <div>
              <strong>{t('import.loadingTitle')}</strong>
              <p>{t('import.loadingCopy')}</p>
            </div>
          </div>
        ) : null}

        {preview ? (
          <section className="preview card" aria-label={t('import.preview')}>
            <div className="preview-head">
              <div className="preview-cover">
                <Cover title={preview.title} remoteUrl={preview.thumbnail_url} />
              </div>
              <div className="preview-title">
                <div className="badge-row">
                  <Badge tone="gold">
                    {t('import.apiVersion', { version: preview.api_version })}
                  </Badge>
                  <Badge>{t('import.canvases', { count: preview.canvas_count })}</Badge>
                  <Badge>
                    {t('import.readableImages', { count: preview.image_canvas_count })}
                  </Badge>
                </div>
                <h2>{preview.title}</h2>
                <p className="preview-creator">
                  {preview.creator || t('import.creatorUnknown')}
                </p>
                {preview.summary ? <p className="preview-summary">{preview.summary}</p> : null}
                <a
                  className="source-link"
                  href={preview.manifest_url}
                  target="_blank"
                  rel="noreferrer noopener"
                >
                  <Icon name="external" size={14} />
                  {preview.manifest_url}
                </a>
              </div>
            </div>

            {stale ? (
              <Callout tone="warning" title={t('import.staleTitle')}>
                {t('import.staleCopy')}
              </Callout>
            ) : null}

            {preview.duplicate_of ? (
              <Callout tone="warning" title={t('import.duplicateTitle')}>
                <p>
                  {t('import.duplicateCopy', {
                    title: preview.duplicate_title ?? preview.title,
                  })}
                </p>
                <Link className="button button-secondary" to={`/books/${preview.duplicate_of}`}>
                  {t('import.openExisting')}
                </Link>
              </Callout>
            ) : null}

            {preview.warnings.length ? (
              <Callout tone="warning" title={t('import.warningsTitle')}>
                <ul className="warning-list">
                  {preview.warnings.map((warning) => (
                    <li key={warning}>{localizeDiagnostic(warning, t, language)}</li>
                  ))}
                </ul>
              </Callout>
            ) : null}

            {!preview.duplicate_of ? (
              <>
                <div className="preview-facts">
                  <dl>
                    <div>
                      <dt>{t('import.language')}</dt>
                      <dd>{preview.language || t('common.notStated')}</dd>
                    </div>
                    <div>
                      <dt>{t('import.date')}</dt>
                      <dd>{preview.date || t('common.notStated')}</dd>
                    </div>
                    <div>
                      <dt>{t('import.provider')}</dt>
                      <dd>{preview.provider || t('common.notStated')}</dd>
                    </div>
                    <div>
                      <dt>{t('import.rights')}</dt>
                      <dd>
                        {preview.rights_uri ? (
                          <a
                            href={safeHttpUrl(preview.rights_uri)}
                            target="_blank"
                            rel="noreferrer noopener"
                          >
                            {t('import.sourceStatement')}
                          </a>
                        ) : preview.rights ? (
                          t('import.seeBelow')
                        ) : (
                          t('common.notStated')
                        )}
                      </dd>
                    </div>
                  </dl>
                </div>

                {preview.rights || preview.required_statement.value ? (
                  <div className="rights-box">
                    <h3>{t('rights.statement')}</h3>
                    <p>{preview.required_statement.value || preview.rights}</p>
                    {preview.rights_uri ? (
                      <a
                        href={safeHttpUrl(preview.rights_uri)}
                        target="_blank"
                        rel="noreferrer noopener"
                      >
                        {t('import.rightsLink')}
                      </a>
                    ) : null}
                  </div>
                ) : (
                  <Callout tone="warning" title={t('import.noRightsTitle')}>
                    {t('import.noRightsCopy')}
                  </Callout>
                )}

                <div className="preview-edit">
                  <div className="section-heading">
                    <h3>{t('import.editableTitle')}</h3>
                    <p>{t('import.editableCopy')}</p>
                  </div>
                  <div className="form-grid">
                    <div className="field">
                      <label htmlFor="preview-title">{t('import.fieldTitle')}</label>
                      <input
                        id="preview-title"
                        value={draft.title}
                        onChange={(event) => updateDraft('title', event.target.value)}
                      />
                    </div>
                    <div className="field">
                      <label htmlFor="preview-creator">{t('import.fieldCreator')}</label>
                      <input
                        id="preview-creator"
                        value={draft.creator}
                        onChange={(event) => updateDraft('creator', event.target.value)}
                      />
                    </div>
                    <div className="field">
                      <label htmlFor="preview-language">{t('import.fieldLanguage')}</label>
                      <input
                        id="preview-language"
                        value={draft.language}
                        onChange={(event) => updateDraft('language', event.target.value)}
                      />
                    </div>
                    <div className="field">
                      <label htmlFor="preview-date">{t('import.fieldDate')}</label>
                      <input
                        id="preview-date"
                        value={draft.date}
                        onChange={(event) => updateDraft('date', event.target.value)}
                      />
                    </div>
                    <div className="field field-wide">
                      <label htmlFor="preview-description">{t('import.fieldDescription')}</label>
                      <textarea
                        id="preview-description"
                        rows={3}
                        value={draft.description}
                        onChange={(event) => updateDraft('description', event.target.value)}
                      />
                    </div>
                    <div className="field field-wide">
                      <label htmlFor="preview-rights">{t('import.fieldRights')}</label>
                      <textarea
                        id="preview-rights"
                        rows={2}
                        value={draft.rights}
                        onChange={(event) => updateDraft('rights', event.target.value)}
                      />
                    </div>
                    <div className="field">
                      <label htmlFor="preview-rights-uri">{t('import.fieldRightsUri')}</label>
                      <input
                        id="preview-rights-uri"
                        value={draft.rights_uri}
                        onChange={(event) => updateDraft('rights_uri', event.target.value)}
                        placeholder="https://…"
                      />
                    </div>
                    <div className="field">
                      <label htmlFor="preview-tags">{t('import.fieldTags')}</label>
                      <input
                        id="preview-tags"
                        value={draft.tags}
                        onChange={(event) => updateDraft('tags', event.target.value)}
                        placeholder={t('import.tagsPlaceholder')}
                      />
                    </div>
                  </div>
                </div>

                <div className="preview-actions">
                  <button
                    type="button"
                    className="button button-primary button-large"
                    onClick={() => void handleImport()}
                    disabled={importing || stale}
                  >
                    <Icon name="plus" size={18} />
                    {importing ? t('import.importing') : t('import.add')}
                  </button>
                  <button type="button" className="button button-ghost" onClick={reset}>
                    {t('common.startOver')}
                  </button>
                  <p className="preview-note">{t('import.note')}</p>
                </div>
              </>
            ) : null}
          </section>
        ) : null}

        {!preview && !loading ? (
          <aside className="import-notes">
            <div className="note-card">
              <span className="note-number">01</span>
              <h2>{t('import.describeTitle')}</h2>
              <p>{t('import.describeCopy')}</p>
            </div>
            <div className="note-card">
              <span className="note-number">02</span>
              <h2>{t('import.readTitle')}</h2>
              <p>{t('import.readCopy')}</p>
            </div>
            <div className="note-card">
              <span className="note-number">03</span>
              <h2>{t('import.keepTitle')}</h2>
              <p>{t('import.keepCopy')}</p>
            </div>
          </aside>
        ) : null}
      </div>
    </div>
  );
}
