const glyphs = {
  student: <><path d="m2.5 8.2 9.5-5 9.5 5-9.5 5-9.5-5Z" opacity=".18"/><path d="m2.5 8.2 9.5-5 9.5 5-9.5 5-9.5-5Z"/><path d="M6.5 10.4v4.2c0 2.2 2.5 4 5.5 4s5.5-1.8 5.5-4v-4.2M21.5 8.2v6"/></>,
  staff: <><circle cx="8.5" cy="8" r="3.2" opacity=".2"/><circle cx="16.6" cy="8.8" r="2.6" opacity=".12"/><path d="M2.7 20c.4-4 2.4-6.1 5.8-6.1s5.4 2.1 5.8 6.1"/><path d="M13.1 14.7c1-.8 2.1-1.1 3.5-1.1 2.8 0 4.5 1.8 4.8 5.4"/><circle cx="8.5" cy="8" r="3.2"/><circle cx="16.6" cy="8.8" r="2.6"/></>,
  shield: <><path d="M12 2.8 20 6v5.7c0 4.9-3.2 8.2-8 9.5-4.8-1.3-8-4.6-8-9.5V6l8-3.2Z" opacity=".16"/><path d="M12 2.8 20 6v5.7c0 4.9-3.2 8.2-8 9.5-4.8-1.3-8-4.6-8-9.5V6l8-3.2Z"/><path d="m8.7 12.1 2.1 2.1 4.7-4.7"/></>,
  bolt: <><path d="m13.8 2.8-8 10.6h5.6l-1.1 7.8 8-11h-5.4l.9-7.4Z" opacity=".18"/><path d="m13.8 2.8-8 10.6h5.6l-1.1 7.8 8-11h-5.4l.9-7.4Z"/></>,
  chart: <><rect x="3" y="13" width="4" height="7" rx="1.4" opacity=".18"/><rect x="10" y="9" width="4" height="11" rx="1.4" opacity=".18"/><rect x="17" y="4" width="4" height="16" rx="1.4" opacity=".18"/><rect x="3" y="13" width="4" height="7" rx="1.4"/><rect x="10" y="9" width="4" height="11" rx="1.4"/><rect x="17" y="4" width="4" height="16" rx="1.4"/></>,
  school: <><path d="M3 9.2 12 4l9 5.2v10.2H3V9.2Z" opacity=".16"/><path d="M3 9.2 12 4l9 5.2M5 10.4v9h14v-9M9 19.4v-5h6v5M2.5 21h19"/><path d="M12 4V2"/></>,
  server: <><rect x="3" y="3" width="18" height="5" rx="1.7" opacity=".16"/><rect x="3" y="9.5" width="18" height="5" rx="1.7" opacity=".12"/><rect x="3" y="16" width="18" height="5" rx="1.7" opacity=".08"/><rect x="3" y="3" width="18" height="5" rx="1.7"/><rect x="3" y="9.5" width="18" height="5" rx="1.7"/><rect x="3" y="16" width="18" height="5" rx="1.7"/><path d="M6 5.5h.01M6 12h.01M6 18.5h.01"/></>,
  sync: <><circle cx="12" cy="12" r="7.6" opacity=".12"/><path d="M19.4 9A7.7 7.7 0 0 0 6.3 6.5L4.6 8.4M4.6 8.4V4.5m0 3.9h4"/><path d="M4.6 15A7.7 7.7 0 0 0 17.7 17.5l1.7-1.9m0 0v3.9m0-3.9h-4"/></>,
  check: <><circle cx="12" cy="12" r="9" opacity=".14"/><circle cx="12" cy="12" r="9"/><path d="m7.8 12.1 2.7 2.8 5.9-6"/></>,
  mail: <><rect x="2.8" y="5" width="18.4" height="14" rx="2.4" opacity=".12"/><rect x="2.8" y="5" width="18.4" height="14" rx="2.4"/><path d="m3.8 7 8.2 6 8.2-6"/></>,
  lock: <><rect x="4.5" y="10" width="15" height="11" rx="2.4" opacity=".12"/><rect x="4.5" y="10" width="15" height="11" rx="2.4"/><path d="M8.2 10V7.3a3.8 3.8 0 0 1 7.6 0V10M12 14.5v2.3"/></>,
  arrow: <path d="M5 12h13M14 7l5 5-5 5"/>,
  back: <path d="M19 12H6M10 7l-5 5 5 5"/>,
}

export function Pictogram({ name, size = 24, className = '' }) {
  return (
    <svg
      className={`pictogram ${className}`.trim()}
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="currentColor"
      stroke="currentColor"
      strokeWidth="1.65"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      {glyphs[name] || glyphs.check}
    </svg>
  )
}
