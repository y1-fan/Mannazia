import type { ReactNode } from 'react';
import { useId } from 'react';
import { Icon, type IconName } from './Icon';
import { classNames } from '../lib';
import { useI18n } from '../i18n';

export function EmptyState({
  title,
  children,
  icon = 'library',
  action,
}: {
  title: string;
  children?: ReactNode;
  icon?: IconName;
  action?: ReactNode;
}) {
  return (
    <div className="empty-state">
      <div className="empty-rune" aria-hidden="true">
        ᛗ
      </div>
      <div className="empty-icon">
        <Icon name={icon} size={26} />
      </div>
      <h2>{title}</h2>
      {children ? <div className="empty-copy">{children}</div> : null}
      {action ? <div className="empty-action">{action}</div> : null}
    </div>
  );
}

export function LoadingBlock({ label }: { label?: string }) {
  const { t } = useI18n();
  return (
    <div className="loading-block" role="status">
      <span className="spinner" aria-hidden="true" />
      <span>{label ?? t('feedback.loading')}</span>
    </div>
  );
}

export function ErrorPanel({
  title,
  message,
  onRetry,
  children,
}: {
  title?: string;
  message: string;
  onRetry?: () => void;
  children?: ReactNode;
}) {
  const { t } = useI18n();
  return (
    <div className="error-panel" role="alert">
      <div className="error-heading">
        <Icon name="alert" size={20} />
        <h2>{title ?? t('feedback.errorTitle')}</h2>
      </div>
      <p>{message}</p>
      {children}
      {onRetry ? (
        <button type="button" className="button button-secondary" onClick={onRetry}>
          <Icon name="refresh" size={16} />
          {t('feedback.tryAgain')}
        </button>
      ) : null}
    </div>
  );
}

export function ProgressBar({
  value,
  label,
  tone = 'gold',
}: {
  value: number;
  label?: string;
  tone?: 'gold' | 'green';
}) {
  const { t } = useI18n();
  const safe = Math.max(0, Math.min(100, Number.isFinite(value) ? value : 0));
  const id = useId();
  return (
    <div className={classNames('progress', `progress-${tone}`)}>
      {label ? (
        <div className="progress-label" id={id}>
          <span>{label}</span>
          <span>{Math.round(safe)}%</span>
        </div>
      ) : null}
      <div
        className="progress-track"
        role="progressbar"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={Math.round(safe)}
        aria-labelledby={label ? id : undefined}
        aria-label={label ? undefined : t('feedback.progress')}
      >
        <span style={{ width: `${safe}%` }} />
      </div>
    </div>
  );
}

export function Callout({
  tone = 'info',
  title,
  children,
}: {
  tone?: 'info' | 'warning' | 'success';
  title?: string;
  children: ReactNode;
}) {
  return (
    <div className={classNames('callout', `callout-${tone}`)}>
      <Icon name={tone === 'warning' ? 'alert' : tone === 'success' ? 'check' : 'info'} size={18} />
      <div>
        {title ? <strong>{title}</strong> : null}
        <div className="callout-body">{children}</div>
      </div>
    </div>
  );
}

export function Badge({
  children,
  tone = 'neutral',
}: {
  children: ReactNode;
  tone?: 'neutral' | 'gold' | 'green';
}) {
  return <span className={classNames('badge', `badge-${tone}`)}>{children}</span>;
}
