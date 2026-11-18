export function HyperBrandMark({ className = "" }: { className?: string }) {
  return (
    <svg
      aria-hidden="true"
      className={`brand-mark ${className}`.trim()}
      fill="none"
      focusable="false"
      viewBox="0 0 32 32"
    >
      <circle cx="16" cy="16" r="12.5" opacity=".38" stroke="currentColor" strokeWidth="1.5" />
      <path
        d="M4 17h6l2.8-5.5 4.1 10 2.8-6H28"
        stroke="currentColor"
        strokeLinecap="round"
        strokeLinejoin="round"
        strokeWidth="2.25"
      />
      <circle cx="27" cy="15.5" fill="var(--info, #06b6d4)" r="2.2" />
    </svg>
  );
}
