import { Link } from 'react-router-dom';
import { EmptyState } from '../components/Feedback';
import { useI18n } from '../i18n';

export function NotFoundPage() {
  const { t } = useI18n();
  return (
    <div className="page">
      <div className="container container-narrow">
        <EmptyState
          title={t('notFound.title')}
          icon="search"
          action={
            <Link className="button button-primary" to="/">
              {t('notFound.return')}
            </Link>
          }
        >
          <p>{t('notFound.copy')}</p>
        </EmptyState>
      </div>
    </div>
  );
}
