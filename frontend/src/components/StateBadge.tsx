import type { BookState, JobState } from '../types';
import { bookStateMeta, classNames, jobStateMeta } from '../lib';
import { useI18n } from '../i18n';

export function StateBadge({
  state,
  kind = 'book',
  className,
}: {
  state: BookState | JobState;
  kind?: 'book' | 'job';
  className?: string;
}) {
  const { t } = useI18n();
  const meta =
    kind === 'book'
      ? bookStateMeta(state as BookState, t)
      : jobStateMeta(state as JobState, t);
  return (
    <span
      className={classNames('state-badge', `tone-${meta.tone}`, className)}
      title={meta.description}
    >
      <span className="state-dot" aria-hidden="true" />
      {meta.label}
    </span>
  );
}
