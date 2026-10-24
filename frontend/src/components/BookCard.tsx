import { Link } from 'react-router-dom';
import type { BookSummary } from '../types';
import { bookProgressPercent, bookStateMeta } from '../lib';
import { useI18n } from '../i18n';
import { Cover } from './Cover';
import { StateBadge } from './StateBadge';

export function BookCard({ book }: { book: BookSummary }) {
  const { t } = useI18n();
  const percent = bookProgressPercent(book.completed_pages, book.total_pages);
  const meta = bookStateMeta(book.download_state, t);
  const offlineLabel =
    book.download_state === 'offline'
      ? t('book.pagesOnNas', { count: book.completed_pages })
      : book.download_state === 'partial'
        ? t('book.pagesLocal', {
            completed: book.completed_pages,
            total: book.total_pages,
          })
        : meta.description;
  const creator = book.creator
    ? t('book.cardAriaCreator', { creator: book.creator })
    : '';

  return (
    <Link
      to={`/books/${book.id}`}
      className="book-card"
      aria-label={t('book.cardAria', {
        title: book.title,
        creator,
        state: meta.label,
      })}
    >
      <div className="book-cover-wrap">
        <Cover
          title={book.title}
          localUrl={book.local_cover_url}
          remoteUrl={book.thumbnail_url}
        />
        <StateBadge state={book.download_state} className="book-badge" />
        {book.download_state === 'partial' || book.download_state === 'offline' ? (
          <span className="book-progress" aria-hidden="true">
            <span style={{ width: `${percent}%` }} />
          </span>
        ) : null}
      </div>
      <div className="book-card-text">
        <h3 className="book-title">{book.title}</h3>
        <p className="book-creator">{book.creator || t('book.creatorUnknown')}</p>
        <p className="book-meta-line">
          <span>
            {book.total_canvases}{' '}
            {book.total_canvases === 1 ? t('common.pageOne') : t('common.pageMany')}
          </span>
          <span aria-hidden="true">·</span>
          <span className="book-meta-status" title={offlineLabel}>
            {offlineLabel}
          </span>
        </p>
        {book.tags.length ? (
          <p className="book-tags">
            {book.tags.slice(0, 3).map((tag) => (
              <span key={tag}>{tag}</span>
            ))}
          </p>
        ) : null}
      </div>
    </Link>
  );
}
