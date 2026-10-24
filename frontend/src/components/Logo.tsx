import { Link } from 'react-router-dom';

export function Logo({ linked = true }: { linked?: boolean }) {
  const content = (
    <>
      <span className="logo-mark-wrap" aria-hidden="true">
        <img src="/mannaz-logo.svg" alt="" className="logo-mark" width={42} height={42} />
      </span>
      <span className="sr-only">Mannazia</span>
    </>
  );
  if (!linked) {
    return (
      <div className="logo" role="img" aria-label="Mannazia">
        {content}
      </div>
    );
  }
  return (
    <Link to="/" className="logo" aria-label="Mannazia">
      {content}
    </Link>
  );
}
