import { Children, useEffect, useId, useRef, useState } from 'react'
import { Icon } from '../icons/Icon'
import { toastBus } from './useToast'

export function WeaveMark({ className = '', monochrome = false }) {
  const rawId = useId().replace(/:/g, '')
  const blueId = `${rawId}-weave-blue`
  const goldId = `${rawId}-weave-gold`

  if (monochrome) return (
    <svg className={`weave-mark weave-mark--monochrome ${className}`.trim()} viewBox="0 0 512 512" fill="none" aria-hidden="true">
      <g stroke="currentColor" strokeWidth="24" strokeLinecap="round" strokeLinejoin="round">
        <path d="M72 174c76 0 82 164 184 164s108-164 184-164" />
        <path d="M72 338c76 0 82-164 184-164s108 164 184 164" />
      </g>
    </svg>
  )

  return (
    <svg className={`weave-mark ${className}`.trim()} viewBox="0 0 512 512" fill="none" aria-hidden="true">
      <defs>
        <linearGradient id={blueId} x1="64" y1="128" x2="448" y2="384" gradientUnits="userSpaceOnUse">
          <stop stopColor="var(--weave-thread-one-start, #60a5fa)" />
          <stop offset="0.45" stopColor="var(--weave-thread-one-mid, #1d4ed8)" />
          <stop offset="1" stopColor="var(--weave-thread-one-end, #1e3a8a)" />
        </linearGradient>
        <linearGradient id={goldId} x1="448" y1="128" x2="64" y2="384" gradientUnits="userSpaceOnUse">
          <stop stopColor="var(--weave-thread-two-start, #fde68a)" />
          <stop offset="0.46" stopColor="var(--weave-thread-two-mid, #f59e0b)" />
          <stop offset="1" stopColor="var(--weave-thread-two-end, #b45309)" />
        </linearGradient>
      </defs>
      <g fill="none" strokeLinecap="round">
        <path d="M72 174c76 0 82 164 184 164s108-164 184-164" stroke="var(--weave-thread-one-halo, #bfdbfe)" strokeWidth="84" opacity=".7" />
        <path d="M72 174c76 0 82 164 184 164s108-164 184-164" stroke={`url(#${blueId})`} strokeWidth="58" />
        <path d="M72 338c76 0 82-164 184-164s108 164 184 164" stroke="var(--weave-thread-two-halo, #fef3c7)" strokeWidth="84" opacity=".78" />
        <path d="M72 338c76 0 82-164 184-164s108 164 184 164" stroke={`url(#${goldId})`} strokeWidth="58" />
        <path d="M188 256h136" stroke="#fff" strokeWidth="18" opacity=".88" />
      </g>
    </svg>
  )
}

export function WeaveLogo({ inverse = false, size = 'normal' }) {
  return (
    <div className={`weave-logo ${inverse ? 'inverse' : ''} ${size === 'large' ? 'large' : ''}`} role="img" aria-label="Weave CBT">
      <WeaveMark />
      <strong className="weave-logo__word">Weave</strong>
      <i className="weave-logo__divider" aria-hidden="true" />
      <span className="weave-logo__cbt">CBT</span>
    </div>
  )
}

export function TenantIdentity({ tenant, inverse = false }) {
  return (
    <div className={`tenant-identity ${inverse ? 'inverse' : ''}`}>
      <span>{tenant.initials}</span>
      <div>
        <strong>{tenant.schoolName}</strong>
        <small>{tenant.nodeName}</small>
      </div>
      {!inverse && <Icon name="chevronDown" size={18} />}
    </div>
  )
}

export function DashboardSchoolIdentity({ schoolName, logoSrc }) {
  return (
    <div className="dashboard-school-identity">
      <span className="dashboard-school-identity__mark">
        {logoSrc ? <img src={logoSrc} alt="" /> : <Icon name="school" size={20} />}
      </span>
      <strong title={schoolName}>{schoolName}</strong>
    </div>
  )
}

export function DashboardAccountMenu({ actor, fallbackName, roleLabel, onSignOut }) {
  const [open, setOpen] = useState(false)
  const accountRef = useRef(null)
  const displayName = actor?.display_name?.trim()
  const primaryLabel = displayName || actor?.email || fallbackName

  useEffect(() => {
    const closeMenu = (event) => {
      if (accountRef.current && !accountRef.current.contains(event.target)) setOpen(false)
    }
    document.addEventListener('pointerdown', closeMenu)
    return () => document.removeEventListener('pointerdown', closeMenu)
  }, [])

  return (
    <div className="dashboard-account" ref={accountRef}>
      <button
        className="dashboard-account__trigger"
        type="button"
        aria-haspopup="menu"
        aria-expanded={open}
        onClick={() => setOpen((current) => !current)}
      >
        <span className="dashboard-account__avatar">{accountInitial(primaryLabel)}</span>
        <span className="dashboard-account__identity">
          <strong>{primaryLabel}</strong>
          <small>{roleLabel}</small>
        </span>
        <Icon name="chevronDown" size={16} />
      </button>
      {open && (
        <div className="dashboard-account__menu" role="menu">
          <button type="button" onClick={onSignOut}><Icon name="logout" size={17} /> Logout</button>
        </div>
      )}
    </div>
  )
}

function accountInitial(value) {
  return String(value || 'User').trim().charAt(0).toUpperCase() || 'U'
}

export function SegmentedControl({ label, value, options, onChange }) {
  return (
    <div className="segmented" role="group" aria-label={label}>
      {options.map(([optionValue, optionLabel]) => (
        <button key={optionValue} type="button" className={value === optionValue ? 'active' : ''} onClick={() => onChange(optionValue)}>
          {optionLabel}
        </button>
      ))}
    </div>
  )
}

export function SelectControl({
  label,
  value,
  options,
  onChange,
  placeholder = 'Select an option',
  disabled = false,
  className = '',
}) {
  const [open, setOpen] = useState(false)
  const rootRef = useRef(null)
  const listboxId = useId()
  const normalized = options.map((option) => (
    Array.isArray(option)
      ? { value: option[0], label: option[1] }
      : option
  ))
  const selected = normalized.find((option) => String(option.value) === String(value))

  useEffect(() => {
    if (!open) return undefined
    const close = (event) => {
      if (event.type === 'keydown' && event.key === 'Escape') {
        setOpen(false)
        return
      }
      if (event.type === 'pointerdown' && rootRef.current && !rootRef.current.contains(event.target)) setOpen(false)
    }
    document.addEventListener('pointerdown', close)
    document.addEventListener('keydown', close)
    return () => {
      document.removeEventListener('pointerdown', close)
      document.removeEventListener('keydown', close)
    }
  }, [open])

  const select = (next) => {
    if (next.disabled) return
    onChange?.(next.value)
    setOpen(false)
  }

  return (
    <div className={`weave-select ${open ? 'is-open' : ''} ${className}`.trim()} ref={rootRef}>
      <button
        type="button"
        className="weave-select__trigger"
        role="combobox"
        aria-label={label}
        aria-controls={listboxId}
        aria-expanded={open}
        aria-haspopup="listbox"
        disabled={disabled}
        onClick={() => setOpen((current) => !current)}
        onKeyDown={(event) => {
          if ((event.key === 'ArrowDown' || event.key === 'ArrowUp') && !open) {
            event.preventDefault()
            setOpen(true)
          }
        }}
      >
        <span className={selected ? '' : 'is-placeholder'}>{selected?.label || placeholder}</span>
        <Icon name="chevronDown" size={17} />
      </button>
      {open && !disabled && (
        <div className="weave-select__menu" id={listboxId} role="listbox" aria-label={label}>
          {normalized.map((option) => {
            const active = String(option.value) === String(value)
            return (
              <button
                key={String(option.value)}
                type="button"
                role="option"
                aria-selected={active}
                className={`weave-select__option ${active ? 'is-selected' : ''}`}
                disabled={option.disabled}
                onClick={() => select(option)}
              >
                <span><strong>{option.label}</strong>{option.description && <small>{option.description}</small>}</span>
                {active && <span className="weave-select__selected-mark" aria-hidden="true">✓</span>}
              </button>
            )
          })}
          {normalized.length === 0 && <span className="weave-select__empty">No options available</span>}
        </div>
      )}
    </div>
  )
}

export function FormField({ label, value, onChange, type = 'text', icon, placeholder }) {
  const [visible, setVisible] = useState(false)
  const inputType = type === 'password' && visible ? 'text' : type

  return (
    <label className="form-field">
      <span>{label}</span>
      <span className="form-field__control">
        {icon && <Icon name={icon} size={20} />}
        <input type={inputType} value={value} placeholder={placeholder} onChange={(event) => onChange(event.target.value)} />
        {type === 'password' && (
          <button
            type="button"
            className="form-field__reveal"
            aria-label={visible ? 'Hide password' : 'Show password'}
            onClick={() => setVisible((current) => !current)}
          >
            <Icon name={visible ? 'eyeOff' : 'eye'} size={20} />
          </button>
        )}
      </span>
    </label>
  )
}

export function Notice({ tone = 'neutral', children }) {
  const id = useId()
  const message = noticeText(children)
  const type = tone === 'danger' ? 'error' : tone === 'neutral' ? 'info' : tone
  useEffect(() => {
    toastBus.show(message, type, { id })
    if (type === 'error') return undefined
    return () => toastBus.remove(id)
  }, [id, message, type])
  return null
}

function noticeText(children) {
  return Children.toArray(children).map((child) => (
    typeof child === 'string' || typeof child === 'number' ? String(child) : noticeText(child.props?.children)
  )).join('')
}

export function StatusBadge({ children, tone = 'neutral' }) {
  return <span className={`status-badge ${tone}`}>{children}</span>
}

export function PageTitle({ title, subtitle }) {
  return <div className="page-title"><h1>{title}</h1>{subtitle && <p>{subtitle}</p>}</div>
}

export function Panel({ title, action, className = '', children }) {
  return (
    <section className={`panel ${className}`}>
      <div className="panel__header">
        <h2>{title}</h2>
        {action}
      </div>
      {children}
    </section>
  )
}

export function Metric({ label, value, helper }) {
  return <div className="metric"><span>{label}</span><strong>{value}</strong>{helper && <small>{helper}</small>}</div>
}

export function FilterBar({ children }) {
  return <div className="filter-bar">{children}</div>
}

export function SearchField({ label, placeholder }) {
  return (
    <label className="search-field">
      <Icon name="search" size={17} />
      <input aria-label={label} placeholder={placeholder} />
    </label>
  )
}

export function DataTable({ columns, rows, onRowClick }) {
  return (
    <div className="table-wrap">
      <table>
        <thead><tr>{columns.map((column) => <th key={column}>{column}</th>)}</tr></thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.join('-')} onClick={() => onRowClick?.(row)}>
              {row.map((cell, index) => <td key={`${cell}-${index}`}>{cell}</td>)}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
