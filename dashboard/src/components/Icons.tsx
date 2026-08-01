// Inline stroke icons (no icon-font/library dependency — the dashboard
// ships as a static bundle behind nginx, and a handful of 16px glyphs
// isn't worth a package). All share one 24-box viewport and inherit
// currentColor so they take the surrounding text token, never a series
// color (the dataviz skill's "text wears text tokens" rule).

interface IconProps {
  size?: number;
}

function svgProps(size: number) {
  return {
    width: size,
    height: size,
    viewBox: "0 0 24 24",
    fill: "none",
    stroke: "currentColor",
    strokeWidth: 1.8,
    strokeLinecap: "round" as const,
    strokeLinejoin: "round" as const,
    "aria-hidden": true,
  };
}

export function IconGrid({ size = 15 }: IconProps) {
  return (
    <svg {...svgProps(size)}>
      <rect x="3" y="3" width="7" height="7" rx="1.5" />
      <rect x="14" y="3" width="7" height="7" rx="1.5" />
      <rect x="3" y="14" width="7" height="7" rx="1.5" />
      <rect x="14" y="14" width="7" height="7" rx="1.5" />
    </svg>
  );
}

export function IconPlay({ size = 15 }: IconProps) {
  return (
    <svg {...svgProps(size)}>
      <path d="M6 4l14 8-14 8V4z" />
    </svg>
  );
}

export function IconPause({ size = 15 }: IconProps) {
  return (
    <svg {...svgProps(size)}>
      <rect x="6" y="4" width="4" height="16" rx="1" />
      <rect x="14" y="4" width="4" height="16" rx="1" />
    </svg>
  );
}

export function IconSkipBack({ size = 15 }: IconProps) {
  return (
    <svg {...svgProps(size)}>
      <path d="M18 5v14L8 12l10-7z" />
      <line x1="5" y1="5" x2="5" y2="19" />
    </svg>
  );
}

export function IconStepBack({ size = 15 }: IconProps) {
  return (
    <svg {...svgProps(size)}>
      <path d="M15 6l-7 6 7 6V6z" />
    </svg>
  );
}

export function IconStepForward({ size = 15 }: IconProps) {
  return (
    <svg {...svgProps(size)}>
      <path d="M9 6l7 6-7 6V6z" />
    </svg>
  );
}

export function IconRestart({ size = 15 }: IconProps) {
  return (
    <svg {...svgProps(size)}>
      <path d="M3 12a9 9 0 1 0 3-6.7" />
      <path d="M3 4v5h5" />
    </svg>
  );
}

export function IconGraph({ size = 15 }: IconProps) {
  return (
    <svg {...svgProps(size)}>
      <circle cx="5" cy="12" r="2.5" />
      <circle cx="19" cy="6" r="2.5" />
      <circle cx="19" cy="18" r="2.5" />
      <line x1="7.3" y1="11" x2="16.7" y2="7" />
      <line x1="7.3" y1="13" x2="16.7" y2="17" />
    </svg>
  );
}

export function IconShield({ size = 15 }: IconProps) {
  return (
    <svg {...svgProps(size)}>
      <path d="M12 3l7 3v6c0 4.4-3 8.2-7 9-4-.8-7-4.6-7-9V6l7-3z" />
    </svg>
  );
}

export function IconAlert({ size = 15 }: IconProps) {
  return (
    <svg {...svgProps(size)}>
      <path d="M12 4l9 16H3l9-16z" />
      <line x1="12" y1="10" x2="12" y2="14" />
      <circle cx="12" cy="17" r="0.6" fill="currentColor" />
    </svg>
  );
}

export function IconCoin({ size = 15 }: IconProps) {
  return (
    <svg {...svgProps(size)}>
      <circle cx="12" cy="12" r="8.5" />
      <path d="M12 7v10M9.5 9.5h4a1.8 1.8 0 0 1 0 3.6h-3a1.8 1.8 0 0 0 0 3.6h4" />
    </svg>
  );
}

export function IconSearch({ size = 15 }: IconProps) {
  return (
    <svg {...svgProps(size)}>
      <circle cx="11" cy="11" r="7" />
      <line x1="16" y1="16" x2="21" y2="21" />
    </svg>
  );
}

export function IconSun({ size = 15 }: IconProps) {
  return (
    <svg {...svgProps(size)}>
      <circle cx="12" cy="12" r="4" />
      <path d="M12 2v2M12 20v2M2 12h2M20 12h2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" />
    </svg>
  );
}

export function IconMoon({ size = 15 }: IconProps) {
  return (
    <svg {...svgProps(size)}>
      <path d="M20 14.5A8.5 8.5 0 0 1 9.5 4a8.5 8.5 0 1 0 10.5 10.5z" />
    </svg>
  );
}

export function IconArrowRight({ size = 14 }: IconProps) {
  return (
    <svg {...svgProps(size)}>
      <line x1="4" y1="12" x2="19" y2="12" />
      <path d="M14 7l5 5-5 5" />
    </svg>
  );
}

export function IconList({ size = 15 }: IconProps) {
  return (
    <svg {...svgProps(size)}>
      <line x1="8" y1="6" x2="21" y2="6" />
      <line x1="8" y1="12" x2="21" y2="12" />
      <line x1="8" y1="18" x2="21" y2="18" />
      <circle cx="4" cy="6" r="1" fill="currentColor" />
      <circle cx="4" cy="12" r="1" fill="currentColor" />
      <circle cx="4" cy="18" r="1" fill="currentColor" />
    </svg>
  );
}

export function IconDatabase({ size = 15 }: IconProps) {
  return (
    <svg {...svgProps(size)}>
      <ellipse cx="12" cy="6" rx="8" ry="3" />
      <path d="M4 6v12c0 1.7 3.6 3 8 3s8-1.3 8-3V6" />
      <path d="M4 12c0 1.7 3.6 3 8 3s8-1.3 8-3" />
    </svg>
  );
}
