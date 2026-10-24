import type { ReactNode, SVGProps } from 'react';

export type IconName =
  | 'search'
  | 'plus'
  | 'download'
  | 'pause'
  | 'play'
  | 'x'
  | 'arrow-left'
  | 'chevron-left'
  | 'chevron-right'
  | 'chevron-down'
  | 'chevron-up'
  | 'fullscreen'
  | 'library'
  | 'settings'
  | 'alert'
  | 'check'
  | 'external'
  | 'trash'
  | 'refresh'
  | 'zoom-in'
  | 'zoom-out'
  | 'fit'
  | 'cloud'
  | 'server'
  | 'info';

const paths: Record<IconName, ReactNode> = {
  search: (
    <>
      <circle cx="10.5" cy="10.5" r="6.5" />
      <path d="m15.5 15.5 4.5 4.5" />
    </>
  ),
  plus: <path d="M12 5v14M5 12h14" />,
  download: (
    <>
      <path d="M12 4v11m0 0 4.2-4.2M12 15l-4.2-4.2" />
      <path d="M5 19.5h14" />
    </>
  ),
  pause: <path d="M9 5.5v13M15 5.5v13" />,
  play: <path d="M8 5.5 18.5 12 8 18.5Z" />,
  x: <path d="m6 6 12 12M18 6 6 18" />,
  'arrow-left': <path d="M19 12H5m0 0 6-6m-6 6 6 6" />,
  'chevron-left': <path d="m14.5 5-7 7 7 7" />,
  'chevron-right': <path d="m9.5 5 7 7-7 7" />,
  'chevron-down': <path d="m5 9 7 7 7-7" />,
  'chevron-up': <path d="m5 15 7-7 7 7" />,
  fullscreen: (
    <path d="M8.5 4H4v4.5M15.5 4H20v4.5M20 15.5V20h-4.5M8.5 20H4v-4.5" />
  ),
  library: (
    <>
      <path d="M4 5.5c2.7-1 5.3-1 8 0v14c-2.7-1-5.3-1-8 0Z" />
      <path d="M12 5.5c2.7-1 5.3-1 8 0v14c-2.7-1-5.3-1-8 0Z" />
    </>
  ),
  settings: (
    <>
      <path d="M4 7h10M18 7h2M4 17h2M10 17h10" />
      <circle cx="16" cy="7" r="2" />
      <circle cx="8" cy="17" r="2" />
    </>
  ),
  alert: (
    <>
      <path d="M12 4 3.5 19h17Z" />
      <path d="M12 9v4.5M12 16.5v.5" />
    </>
  ),
  check: <path d="m5 12.5 4.5 4.5L19 6.5" />,
  external: (
    <>
      <path d="M13 5h6v6M19 5l-8 8" />
      <path d="M19 14v5H5V5h5" />
    </>
  ),
  trash: (
    <>
      <path d="M5 7h14M9.5 7V4.5h5V7M7 7l1 13h8l1-13" />
      <path d="M10 11v5M14 11v5" />
    </>
  ),
  refresh: (
    <>
      <path d="M20 12a8 8 0 1 1-2.3-5.6" />
      <path d="M20 4v5h-5" />
    </>
  ),
  'zoom-in': (
    <>
      <circle cx="10.5" cy="10.5" r="6.5" />
      <path d="m15.5 15.5 4.5 4.5M10.5 7.5v6M7.5 10.5h6" />
    </>
  ),
  'zoom-out': (
    <>
      <circle cx="10.5" cy="10.5" r="6.5" />
      <path d="m15.5 15.5 4.5 4.5M7.5 10.5h6" />
    </>
  ),
  fit: <path d="M9 4H4v5M15 4h5v5M20 15v5h-5M9 20H4v-5M8 8l8 8M16 8l-8 8" />,
  cloud: (
    <path d="M7.5 18.5h9.8a3.7 3.7 0 0 0 .6-7.3A6 6 0 0 0 6.4 10a4.3 4.3 0 0 0 1.1 8.5Z" />
  ),
  server: (
    <>
      <rect x="4" y="5" width="16" height="5" rx="1" />
      <rect x="4" y="14" width="16" height="5" rx="1" />
      <path d="M7.5 7.5h.01M7.5 16.5h.01" />
    </>
  ),
  info: (
    <>
      <circle cx="12" cy="12" r="8" />
      <path d="M12 11v5M12 8v.5" />
    </>
  ),
};

export function Icon({
  name,
  size = 20,
  className,
  ...props
}: { name: IconName; size?: number; className?: string } & SVGProps<SVGSVGElement>) {
  return (
    <svg
      aria-hidden="true"
      focusable="false"
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.6"
      strokeLinecap="round"
      strokeLinejoin="round"
      className={className}
      {...props}
    >
      {paths[name]}
    </svg>
  );
}
