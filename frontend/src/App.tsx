import { Route, Routes } from 'react-router-dom';
import { lazy, Suspense } from 'react';
import { SiteLayout } from './components/SiteLayout';
import { BookshelfPage } from './pages/BookshelfPage';
import { ImportPage } from './pages/ImportPage';
import { BookDetailPage } from './pages/BookDetailPage';
import { DownloadsPage } from './pages/DownloadsPage';
import { SettingsPage } from './pages/SettingsPage';
import { NotFoundPage } from './pages/NotFoundPage';
import { LoadingBlock } from './components/Feedback';
import { useI18n } from './i18n';

const ReaderPage = lazy(() =>
  import('./pages/ReaderPage').then((module) => ({ default: module.ReaderPage })),
);

export default function App() {
  const { t } = useI18n();
  return (
    <Routes>
      <Route
        path="/books/:bookId/read"
        element={
          <Suspense
            fallback={
              <div className="reader-shell">
                <div className="reader-loading">
                  <LoadingBlock label={t('reader.opening')} />
                </div>
              </div>
            }
          >
            <ReaderPage />
          </Suspense>
        }
      />
      <Route element={<SiteLayout />}>
        <Route index element={<BookshelfPage />} />
        <Route path="import" element={<ImportPage />} />
        <Route path="books/:bookId" element={<BookDetailPage />} />
        <Route path="downloads" element={<DownloadsPage />} />
        <Route path="settings" element={<SettingsPage />} />
        <Route path="*" element={<NotFoundPage />} />
      </Route>
    </Routes>
  );
}
