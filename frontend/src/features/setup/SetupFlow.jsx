import { useEffect, useState } from 'react'
import { RiGraduationCapLine } from '@remixicon/react'
import { Pictogram } from '../../shared/icons/Pictogram'
import { Notice, WeaveMark } from '../../shared/ui'
import './setup.css'

function SetupHeader() {
  return (
    <header className="setup-header">
      <div className="setup-logo" role="img" aria-label="Weave">
        <WeaveMark />
        <strong>Weave</strong>
      </div>
    </header>
  )
}

const welcomeDescription = "This CBT server needs to be connected to your school's Weave account before it can be used."
const lockupDescription = 'EXAMS\nMADE\nSIMPLE'
const TYPEWRITER_CHAR_DELAY_MS = 32
const TYPEWRITER_PAUSE_MS = 2500
const LOCKUP_TYPEWRITER_PAUSE_MS = 1800

function TypewriterText({ text, className, as: Tag = 'p', charDelayMs = TYPEWRITER_CHAR_DELAY_MS, pauseMs = TYPEWRITER_PAUSE_MS }) {
  const [loopKey, setLoopKey] = useState(0)
  const visibleText = text.replace(/\n/g, '')

  useEffect(() => {
    const typingMs = visibleText.length * charDelayMs + 10
    let timeoutId
    const loop = () => {
      setLoopKey((key) => key + 1)
      timeoutId = setTimeout(loop, typingMs + pauseMs)
    }
    timeoutId = setTimeout(loop, typingMs + pauseMs)
    return () => clearTimeout(timeoutId)
  }, [visibleText, charDelayMs, pauseMs])

  let charIndex = 0

  return (
    <Tag key={loopKey} className={className} aria-label={visibleText}>
      {Array.from(text).map((character, index) => {
        if (character === '\n') return <br key={`br-${index}`} aria-hidden="true" />
        const delay = charIndex * (charDelayMs / 1000)
        charIndex += 1
        return (
          <span
            key={`${character}-${index}`}
            aria-hidden="true"
            className="setup-typewriter__char"
            style={{ '--typing-delay': `${delay}s` }}
          >
            {character}
          </span>
        )
      })}
    </Tag>
  )
}

export function SetupFlow({ view, error, installation, dispatch, onPair }) {
  const [pairingCode, setPairingCode] = useState('')
  const [serverName, setServerName] = useState('')
  const [localError, setLocalError] = useState('')

  const nextCode = () => {
    if (pairingCode.trim().length < 8 || pairingCode.trim().length > 20) {
      setLocalError('Enter the complete pairing code (8–20 characters).')
      return
    }
    setLocalError('')
    dispatch({ type: 'view', view: 'server-name' })
  }

  const submitName = () => {
    if (serverName.trim().length < 2 || serverName.trim().length > 150) {
      setLocalError('Use a server name between 2 and 150 characters.')
      return
    }
    setLocalError('')
    onPair({ pairingCode: pairingCode.trim().toUpperCase(), serverName: serverName.trim() })
  }

  const codeCharacters = pairingCode.slice(0, 8).padEnd(8, ' ').split('')

  return (
    <main className={`setup-shell setup-shell--${view}`}>
      {view === 'welcome' && <SetupHeader />}

      {view === 'welcome' && (
        <section className="setup-welcome setup-enter">
          <div className="setup-welcome__copy">
            <h1>Welcome to<br />Weave <em>CBT</em></h1>
            <TypewriterText text={welcomeDescription} className="setup-typewriter" />
            <button className="setup-primary setup-primary--welcome" onClick={() => dispatch({ type: 'view', view: 'pairing-code' })}>
              Get Started <Pictogram name="arrow" size={19} />
            </button>
          </div>

          <div className="setup-welcome__blue-panel" aria-hidden="true">
            <RiGraduationCapLine className="setup-cap-icon setup-cap-icon--top" />
            <TypewriterText
              as="div"
              text={lockupDescription}
              className="setup-blue-lockup setup-typewriter setup-typewriter--lockup"
              pauseMs={LOCKUP_TYPEWRITER_PAUSE_MS}
            />
            <RiGraduationCapLine className="setup-cap-icon setup-cap-icon--bottom" />
          </div>
        </section>
      )}

      {view === 'pairing-code' && (
        <>
          <div className="setup-stage-nav">
            <button className="setup-primary setup-primary--nav" type="button" onClick={() => dispatch({ type: 'view', view: 'welcome' })}>
              <Pictogram name="back" size={18} /> Back
            </button>
          </div>
          <section className="setup-stage setup-stage--code setup-enter">
          <div className="setup-card setup-card--code">
            <h1>Enter Pairing Code</h1>
            <p>Use the pairing code from your Weave school account to connect this server.</p>
            <form onSubmit={(event) => { event.preventDefault(); nextCode() }}>
              <label className="setup-visually-hidden" htmlFor="pairing-code">Pairing Code</label>
              <div className="setup-code-entry">
                <input
                  id="pairing-code"
                  className="setup-code-native"
                  autoFocus
                  autoComplete="one-time-code"
                  maxLength="20"
                  value={pairingCode}
                  onChange={(event) => { setPairingCode(event.target.value.toUpperCase()); setLocalError('') }}
                  aria-describedby="pairing-code-help"
                />
                <div className="setup-code-tiles" aria-hidden="true">
                  {codeCharacters.map((character, index) => (
                    <span key={index} className={index === Math.min(pairingCode.length, 7) ? 'current' : ''}>{character.trim()}</span>
                  ))}
                </div>
              </div>
              {pairingCode.length > 8 && <small className="setup-code-more">{pairingCode.length} characters entered</small>}
              {localError && <Notice tone="danger">{localError}</Notice>}
              <button className="setup-primary" type="submit">Continue <Pictogram name="arrow" size={19} /></button>
            </form>
            <small id="pairing-code-help" className="setup-help">Enter or paste the code from your Weave school account.</small>
          </div>
          </section>
        </>
      )}

      {view === 'server-name' && (
        <>
          <div className="setup-stage-nav">
            <button className="setup-primary setup-primary--nav" type="button" onClick={() => dispatch({ type: 'view', view: 'pairing-code' })}>
              <Pictogram name="back" size={18} /> Back
            </button>
          </div>
          <section className="setup-stage setup-stage--server setup-enter">
            <div className="setup-card setup-card--code">
              <div className="setup-icon"><Pictogram name="server" size={30} /></div>
              <h1>Set a server name</h1>
              <p>Give this CBT server a name to easily identify it in your Weave account.</p>
              <form onSubmit={(event) => { event.preventDefault(); submitName() }}>
                <label htmlFor="server-name">Server Name</label>
                <div className="setup-input-with-icon">
                  <Pictogram name="server" size={18} />
                  <input
                    id="server-name"
                    autoFocus
                    maxLength="150"
                    value={serverName}
                    onChange={(event) => { setServerName(event.target.value); setLocalError('') }}
                    placeholder="e.g. Main Lab, Block A, School Hall"
                  />
                </div>
                {localError && <Notice tone="danger">{localError}</Notice>}
                <button className="setup-primary" type="submit">Complete Setup <Pictogram name="arrow" size={19} /></button>
              </form>
            </div>
          </section>
        </>
      )}

      {view === 'pairing' && (
        <section className="setup-stage setup-stage--pairing setup-enter" aria-live="polite">
          <div className="setup-pairing-card">
            {!error && (
              <div className="setup-sync-visual" aria-hidden="true">
                <div className="setup-sync-orbit">
                  <span className="setup-sync-orbit__ring" />
                  <span className="setup-sync-orbit__ring setup-sync-orbit__ring--two" />
                  <div className="setup-sync-orbit__icon"><Pictogram name="sync" size={34} /></div>
                </div>
                <div className="setup-sync-flow">
                  <span className="setup-sync-node"><Pictogram name="server" size={22} /></span>
                  <span className="setup-sync-track">
                    <i /><i /><i /><i /><i />
                  </span>
                  <span className="setup-sync-node"><Pictogram name="school" size={22} /></span>
                </div>
                <div className="setup-sync-rail"><span /></div>
              </div>
            )}
            <h1>{error ? 'Pairing needs attention' : 'Pairing with Weave...'}</h1>
            <p>{error ? 'The server is still unpaired. Review the message and retry with the same details.' : 'Verifying your code and connecting this server to your school account.'}</p>
            {error ? (
              <>
                <Notice tone="danger">{error}</Notice>
                <button className="setup-primary" onClick={submitName}>Retry Pairing <Pictogram name="arrow" size={19} /></button>
                <button className="setup-back" onClick={() => dispatch({ type: 'view', view: 'server-name' })}><Pictogram name="back" size={18} /> Edit server name</button>
              </>
            ) : (
              <div className="setup-progress-list" aria-label="Pairing activity">
                {['Validating pairing code', 'Connecting to Weave', 'Finalizing setup'].map((label, index) => (
                  <div key={label} className={index === 0 ? 'is-complete' : index === 1 ? 'is-active' : ''}>
                    <span className="setup-progress-spinner">{index === 0 ? <Pictogram name="check" size={14} /> : null}</span>
                    <b>{label}</b>
                  </div>
                ))}
              </div>
            )}
            {!error && <small className="setup-help">This may take a few seconds...</small>}
          </div>
        </section>
      )}

      {view === 'paired-success' && (
        <section className="setup-stage setup-stage--success setup-enter">
          <div className="setup-success-card">
            <div className="setup-confetti" aria-hidden="true">{Array.from({ length: 10 }, (_, index) => <i key={index} />)}</div>
            <div className="setup-success-check"><Pictogram name="check" size={40} /></div>
            <h1>Successfully Paired!</h1>
            <p>This CBT server is now connected to {installation.status?.tenant_name || 'your Weave school account'}.</p>
            <div className="setup-success-info"><Pictogram name="server" size={21} /><span>Your server is set up and ready to use. School data may continue preparing in the background.</span></div>
            {installation.status?.hostname && (
              <div className="setup-success-info" aria-label="Assigned CBT server hostname">
                <Pictogram name="server" size={21} />
                <span style={{ overflowWrap: 'anywhere' }}>
                  <strong>Assigned HTTPS address:</strong> https://{installation.status.hostname}
                  <small style={{ display: 'block' }}>HTTPS becomes available after certificate setup and school LAN DNS configuration.</small>
                </span>
              </div>
            )
            <button className="setup-primary" onClick={() => dispatch({ type: 'view', view: 'landing' })}>Continue to Home <Pictogram name="arrow" size={19} /></button>
          </div>
          <p className="product-script setup-success-script" aria-hidden="true">Same tools.<br />Brighter learning.</p>
        </section>
      )}

    </main>
  )
}
