import { Link } from 'react-router-dom';
import { useMemo, useState } from 'react';
import { api } from '../api';
import { BookCard } from '../components/BookCard';
import { EmptyState, ErrorPanel, LoadingBlock } from '../components/Feedback';
import { Icon } from '../components/Icon';
import { useAsync, useDebouncedValue, useDocumentTitle } from '../hooks';
import { useErrorMessage, useI18n } from '../i18n';
import type { BookState } from '../types';

export function BookshelfPage() {
  const { t } = useI18n();
  const errorMessage = useErrorMessage();
  useDocumentTitle(t('shelf.title'));
  const [query, setQuery] = useState('');
  const [state, setState] = useState<BookState | ''>('');
  const debouncedQuery = useDebouncedValue(query, 250);
  const filters = useMemo(
    () => [
      { value: '' as const, label: t('shelf.filterAll') },
      { value: 'offline' as const, label: t('shelf.filterOffline') },
      { value: 'partial' as const, label: t('shelf.filterPartial') },
      { value: 'downloading' as const, label: t('shelf.filterDownloading') },
      { value: 'online' as const, label: t('shelf.filterOnline') },
      { value: 'error' as const, label: t('shelf.filterError') },
    ],
    [t],
  );
  const { data, loading, error, reload } = useAsync(
    () => api.listBooks({ query: debouncedQuery, state, limit: 200 }),
    `${debouncedQuery}|${state}`,
  );
  const books = data?.items ?? [];
  const hasFilters = Boolean(debouncedQuery || state);

  return (
    <div className="page bookshelf-page">
      <div className="container">
        <header className="page-heading shelf-heading">
          <div>
            <h1>{t('shelf.title')}</h1>
            <p className="lede">
              {data
                ? t(data.total === 1 ? 'shelf.volumesOne' : 'shelf.volumesMany', {
                    count: data.total,
                  })
                : t('feedback.loading')}
            </p>
          </div>
        </header>

        {data && (data.total > 0 || hasFilters) ? (
          <div className="shelf-toolbar">
            <div className="search-field">
              <Icon name="search" size={18} />
              <input
                type="search"
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                placeholder={t('shelf.searchPlaceholder')}
                aria-label={t('shelf.searchAria')}
              />
              {query ? (
                <button
                  type="button"
                  className="icon-button search-clear"
                  onClick={() => setQuery('')}
                  aria-label={t('shelf.clearSearch')}
                >
                  <Icon name="x" size={15} />
                </button>
              ) : null}
            </div>
            <div className="filter-chips" role="group" aria-label={t('shelf.filterAria')}>
              {filters.map((filter) => (
                <button
                  key={filter.value || 'all'}
                  type="button"
                  className={state === filter.value ? 'chip is-active' : 'chip'}
                  aria-pressed={state === filter.value}
                  onClick={() => setState(filter.value)}
                >
                  {filter.label}
                </button>
              ))}
            </div>
          </div>
        ) : null}

        {error && !data ? (
          <ErrorPanel
            title={t('shelf.errorTitle')}
            message={errorMessage(error)}
            onRetry={reload}
          />
        ) : null}

        {loading && !data ? <LoadingBlock label={t('shelf.loading')} /> : null}

        {data && books.length === 0 ? (
          hasFilters ? (
            <EmptyState
              title={t('shelf.noMatchTitle')}
              icon="search"
              action={
                <button
                  type="button"
                  className="button button-secondary"
                  onClick={() => {
                    setQuery('');
                    setState('');
                  }}
                >
                  {t('shelf.clearFilters')}
                </button>
              }
            >
              <p>{t('shelf.noMatchCopy')}</p>
            </EmptyState>
          ) : (
            <EmptyState
              title={t('shelf.emptyTitle')}
              action={
                <Link to="/import" className="button button-primary button-large">
                  <Icon name="plus" size={18} />
                  {t('shelf.emptyAction')}
                </Link>
              }
            >
              <p>{t('shelf.emptyCopy')}</p>
              <p className="muted">{t('shelf.emptyNote')}</p>
            </EmptyState>
          )
        ) : null}

        {books.length > 0 ? (
          <>
            <div className="book-grid">
              {books.map((book) => (
                <BookCard key={book.id} book={book} />
              ))}
            </div>
            {data && data.total > books.length ? (
              <p className="shelf-note muted">
                {t('shelf.showing', { shown: books.length, total: data.total })}
              </p>
            ) : null}
          </>
        ) : null}
      </div>
    </div>
  );
}
