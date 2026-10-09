import { useEffect, useState } from 'react'
import { RiGraduationCapLine } from '@remixicon/react'
import { getLocalBrandLogoSrc } from '../../api/branding'
import { Pictogram } from '../../shared/icons/Pictogram'
import { Notice } from '../../shared/ui'
import './auth.css'

const LOCKUP_DESCRIPTION = 'EXAMS\nMADE\nSIMPLE'
const TYPEWRITER_CHAR_DELAY_MS = 32
const LOCKUP_TYPEWRITER_PAUSE_MS = 1800

function LoginTypewriterText({ text, className, as: Tag = 'p', pauseMs = LOCKUP_TYPEWRITER_PAUSE_MS }) {
  const [loopKey, setLoopKey] = useState(0)
  const visibleText = text.replace(/\n/g, '')

  useEffect(() => {
    const typingMs = visibleText.length * TYPEWRITER_CHAR_DELAY_MS + 10
    let timeoutId
    const loop = () => {
      setLoopKey((key) => key + 1)
      timeoutId = setTimeout(loop, typingMs + pauseMs)
    }
    timeoutId = setTimeout(loop, typingMs + pauseMs)
    return () => clearTimeout(timeoutId)
  }, [visibleText, pauseMs])

  let charIndex = 0

  return (
    <Tag key={loopKey} className={className} aria-label={visibleText}>
      {Array.from(text).map((character, index) => {
        if (character === '\n') return <br key={`br-${index}`} aria-hidden="true" />
        const delay = charIndex * (TYPEWRITER_CHAR_DELAY_MS / 1000)
        charIndex += 1
        return (
          <span
            key={`${character}-${index}`}
            aria-hidden="true"
            className="login-typewriter__char"
            style={{ '--typing-delay': `${delay}s` }}
          >
            {character}
          </span>
        )
      })}
    </Tag>
  )
}

export function LoginField({ label, type = 'text', value, onChange, placeholder, autoComplete = 'off', name, required = true }) {
  return (
    <label className="login-field">
      <span>{label}</span>
      <input
        className="login-field__input"
        name={name}
        type={type}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        placeholder={placeholder}
        autoComplete={autoComplete}
        required={required}
      />
    </label>
  )
}

export function LoginShell({ kind, title, subtitle, branding, children, error, loading, onSubmit, onBack }) {
  const logoSrc = getLocalBrandLogoSrc(branding)
  const tenantName = branding?.school_name?.trim() || 'School'

  return (
    <main className={`weave-login-page weave-login-page--${kind}`}>
      <div className="weave-login-stage-nav">
        <button className="weave-login-nav-btn" type="button" onClick={onBack}>
          <Pictogram name="back" size={18} /> Back to Home
        </button>
      </div>

      <section className="weave-login-welcome weave-login-enter">
        <div className="weave-login-panel" aria-hidden="true">
          <div className="weave-login-panel__brand">
            {logoSrc ? (
              <img className="weave-login-tenant-logo" src={logoSrc} alt="" />
            ) : (
              <span className="weave-login-tenant-mark"><Pictogram name="school" size={28} /></span>
            )}
            <strong>{tenantName}</strong>
          </div>
          <RiGraduationCapLine className="weave-login-cap weave-login-cap--top" />
          <div className="weave-login-panel__lockup">
            <LoginTypewriterText
              as="div"
              text={LOCKUP_DESCRIPTION}
              className="weave-login-lockup login-typewriter login-typewriter--lockup"
            />
          </div>
          <RiGraduationCapLine className="weave-login-cap weave-login-cap--bottom" />
        </div>

        <div className="weave-login-form-side">
          <section className="weave-login-card">
            <header className="weave-login-card__head">
              <h1>{title}</h1>
              <p>{subtitle}</p>
            </header>
            <form
              className="weave-login-form"
              autoComplete="off"
              onSubmit={(event) => { event.preventDefault(); onSubmit() }}
            >
              <div className="weave-login-form__fields">{children}</div>
              {error && <Notice tone="danger" dismissOnUnmount>{error}</Notice>}
              <button className="weave-login-submit" type="submit" disabled={loading}>
                {loading ? 'Checking...' : 'Sign In'}
              </button>
            </form>
          </section>
        </div>
      </section>
    </main>
  )
}
