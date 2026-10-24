import { NavLink, Outlet, Link } from 'react-router-dom';
import { Logo } from './Logo';
import { Icon } from './Icon';
import { LanguageSwitch } from './LanguageSwitch';
import { useI18n } from '../i18n';

export function SiteLayout() {
  const { t } = useI18n();
  return (
    <div className="app-shell">
      <a className="skip-link" href="#main">
        {t('nav.skip')}
      </a>
      <header className="site-header">
        <div className="container header-inner">
          <Logo />
          <nav className="site-nav" aria-label={t('nav.primary')}>
            <NavLink to="/" end aria-label={t('nav.library')}>
              <Icon name="library" size={17} />
              <span>{t('nav.library')}</span>
            </NavLink>
            <NavLink to="/downloads" aria-label={t('nav.downloads')}>
              <Icon name="download" size={17} />
              <span>{t('nav.downloads')}</span>
            </NavLink>
            <NavLink to="/settings" aria-label={t('nav.settings')}>
              <Icon name="settings" size={17} />
              <span>{t('nav.settings')}</span>
            </NavLink>
          </nav>
          <LanguageSwitch />
          <Link
            to="/import"
            className="button button-primary header-import"
            aria-label={t('nav.importAria')}
          >
            <Icon name="plus" size={17} />
            <span>{t('nav.import')}</span>
          </Link>
        </div>
      </header>
      <main id="main" className="site-main">
        <Outlet />
      </main>
      <footer className="site-footer">
        <div className="container footer-inner">
          <p className="footer-brand">
            <span className="rune-small" aria-hidden="true">
              ᛗ
            </span>{' '}
            Mannazia
          </p>
          <p className="footer-links">
            <a href="/api/docs">{t('footer.apiDocs')}</a>
            <span aria-hidden="true">·</span>
            <span>{t('footer.spec')}</span>
          </p>
        </div>
      </footer>
    </div>
  );
}
