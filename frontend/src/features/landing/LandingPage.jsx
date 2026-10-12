import { useEffect, useState } from 'react'
import { Pictogram } from '../../shared/icons/Pictogram'
import { WeaveMark } from '../../shared/ui'
import './landing.css'

const WORDMARK_TEXT = 'Weave'
const TYPEWRITER_CHAR_DELAY_MS = 145
const TYPEWRITER_PAUSE_MS = 3200

function LandingWordmarkTypewriter() {
  const [loopKey, setLoopKey] = useState(0)

  useEffect(() => {
    const typingMs = WORDMARK_TEXT.length * TYPEWRITER_CHAR_DELAY_MS + 10
    let timeoutId
    const loop = () => {
      setLoopKey((key) => key + 1)
      timeoutId = setTimeout(loop, typingMs + TYPEWRITER_PAUSE_MS)
    }
    timeoutId = setTimeout(loop, typingMs + TYPEWRITER_PAUSE_MS)
    return () => clearTimeout(timeoutId)
  }, [])

  return (
    <div key={loopKey} className="landing-wordmark weave-logo large" aria-label={WORDMARK_TEXT}>
      {Array.from(WORDMARK_TEXT).map((character, index) => (
        <span
          key={`${character}-${index}`}
          aria-hidden="true"
          className="landing-typewriter__char weave-logo__word"
          style={{ '--typing-delay': `${index * (TYPEWRITER_CHAR_DELAY_MS / 1000)}s` }}
        >
          {character}
        </span>
      ))}
    </div>
  )
}

export function LandingPage({ dispatch, audience = 'combined' }) {
  const openLogin = (kind) => {
    dispatch({ type: 'view', view: kind === 'student' ? 'student-login' : 'staff-login' })
  }

  const showStudentLogin = audience === 'combined' || audience === 'student'
  const showStaffLogin = audience === 'combined' || audience === 'staff'

  return (
    <main className="landing-page">
      <nav className="landing-nav" aria-label="Sign in">
        {showStudentLogin && (
          <button className="landing-primary" type="button" onClick={() => openLogin('student')}>
            Login as Student <Pictogram name="student" size={18} />
          </button>
        )}
        {showStaffLogin && (
          <button
            className={`landing-primary${showStudentLogin ? ' landing-primary--ghost' : ''}`}
            type="button"
            onClick={() => openLogin('staff')}
          >
            Login as Staff <Pictogram name="staff" size={18} />
          </button>
        )}
      </nav>

      <section className="landing-center landing-enter" aria-label="Weave">
        <WeaveMark className="landing-mark" />
        <LandingWordmarkTypewriter />
      </section>
    </main>
  )
}
