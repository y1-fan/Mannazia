import { useI18n } from '../i18n';

export function LanguageSwitch({ compact = false }: { compact?: boolean }) {
  const { language, t, toggleLanguage } = useI18n();
  const visible = language === 'en' ? '中文' : 'EN';
  const nextLabel = language === 'en' ? t('lang.switchToZh') : t('lang.switchToEn');
  return (
    <button
      type="button"
      className={compact ? 'language-switch language-switch-compact' : 'language-switch'}
      onClick={toggleLanguage}
      aria-label={`${visible} — ${nextLabel}`}
      title={nextLabel}
    >
      {visible}
    </button>
  );
}
