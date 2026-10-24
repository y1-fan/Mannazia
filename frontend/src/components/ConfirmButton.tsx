import { useEffect, useRef, useState } from 'react';
import { classNames } from '../lib';
import { useI18n } from '../i18n';

export function ConfirmButton({
  label,
  confirmLabel,
  onConfirm,
  className = 'button button-secondary',
  busy = false,
  disabled = false,
  title,
}: {
  label: string;
  confirmLabel?: string;
  onConfirm: () => void;
  className?: string;
  busy?: boolean;
  disabled?: boolean;
  title?: string;
}) {
  const { t } = useI18n();
  const [armed, setArmed] = useState(false);
  const timer = useRef<number | null>(null);

  useEffect(() => {
    return () => {
      if (timer.current !== null) window.clearTimeout(timer.current);
    };
  }, []);

  const handleClick = () => {
    if (busy) return;
    if (!armed) {
      setArmed(true);
      timer.current = window.setTimeout(() => setArmed(false), 4000);
      return;
    }
    if (timer.current !== null) window.clearTimeout(timer.current);
    setArmed(false);
    onConfirm();
  };

  return (
    <button
      type="button"
      className={classNames(className, armed && 'is-armed')}
      onClick={handleClick}
      disabled={disabled || busy}
      title={title}
      aria-live="polite"
    >
      {busy ? t('common.working') : armed ? (confirmLabel ?? t('common.confirm')) : label}
    </button>
  );
}
