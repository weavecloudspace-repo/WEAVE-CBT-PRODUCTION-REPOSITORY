import { Pictogram } from '../../shared/icons/Pictogram'
import { Notice, WeaveLogo } from '../../shared/ui'
import { useInitialSyncStatus } from './useInitialSyncStatus'
import './sync.css'

const stages = [
  ['sync', 'Connecting to school data'],
  ['school', 'Preparing academic structure'],
  ['student', 'Preparing student records'],
  ['staff', 'Preparing teacher assignments'],
  ['server', 'Finalizing local CBT environment'],
]

export function InitialSyncPage({ error, status, dispatch }) {
  const { readyAnimation, retrying, retry } = useInitialSyncStatus(dispatch)

  return (
    <main className="initial-sync-page">
      <header className="initial-sync-header">
        <div><WeaveLogo /><small>Exams made simple.</small></div>
      </header>

      <section className={`initial-sync-card ${readyAnimation ? 'is-ready' : ''}`} aria-live="polite">
        <div className="initial-sync-orbit" aria-hidden="true">
          <span className="initial-sync-orbit__ring" />
          <span className="initial-sync-orbit__ring initial-sync-orbit__ring--two" />
          <div className="initial-sync-icon"><Pictogram name={readyAnimation ? 'check' : 'sync'} size={38} /></div>
        </div>

        <span className="product-kicker">WEAVE CBT SERVER</span>
        <h1>{readyAnimation ? 'Your server is ready' : 'Preparing your CBT server'}</h1>
        <p>{readyAnimation ? 'School data is ready. Opening your workspace.' : 'We’re securely preparing your school data for local examination use.'}</p>

        {!readyAnimation && (
          <>
            <div className="initial-sync-journey" aria-label="Preparation activity">
              {stages.map(([icon, label], index) => (
                <div key={label} style={{ '--sync-delay': `${index * .3}s` }}>
                  <span><Pictogram name={icon} size={20} /></span>
                  <b>{label}</b>
                  <i />
                </div>
              ))}
            </div>
            <div className="initial-sync-rail" aria-hidden="true"><span /></div>
            <small className="initial-sync-note">The animation shows preparation activity. The local server decides when setup is actually complete.</small>
          </>
        )}

        {(error || status?.last_error) && !readyAnimation && (
          <div className="initial-sync-error">
            <Notice tone="danger">{error || status.last_error}</Notice>
            <button onClick={retry} disabled={retrying}>{retrying ? 'Retrying...' : 'Retry synchronization'}</button>
          </div>
        )}
      </section>

      <footer className="initial-sync-footer">
        <span><b>WEAVE CBT</b> • LOCAL TODAY. BRIGHTER TOMORROW.</span>
        <span><i />Preparing locally. Ready when your school is.</span>
      </footer>
    </main>
  )
}
