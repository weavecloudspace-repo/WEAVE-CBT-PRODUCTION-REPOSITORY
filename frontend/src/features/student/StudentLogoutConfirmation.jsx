import { useEffect, useRef, useState } from 'react'

export function StudentLogoutConfirmation({ children, onLogout }) {
  const [logoutRequest, setLogoutRequest] = useState(null)
  const dialogRef = useRef(null)

  useEffect(() => {
    if (logoutRequest) dialogRef.current?.showModal()
  }, [logoutRequest])

  const requestLogout = (options = {}) => setLogoutRequest(options)
  const cancelLogout = () => setLogoutRequest(null)

  return (
    <>
      {children(requestLogout)}
      {logoutRequest && (
        <dialog
          ref={dialogRef}
          className="student-logout-dialog"
          aria-labelledby="student-logout-title"
          aria-describedby="student-logout-description"
          onCancel={cancelLogout}
          onClose={cancelLogout}
        >
          <h2 id="student-logout-title">{logoutRequest.timerContinues ? 'Log out during examination?' : 'Confirm logout'}</h2>
          <p id="student-logout-description">
            {logoutRequest.timerContinues
              ? 'Your saved answers will remain available, but your examination timer will continue running while you are logged out.'
              : 'Are you sure you want to log out?'}
          </p>
          <div className="student-logout-dialog__actions">
            <button className="premium-btn-secondary" type="button" autoFocus onClick={cancelLogout}>Cancel</button>
            <button className="premium-btn-primary" type="button" onClick={() => {
              setLogoutRequest(null)
              onLogout()
            }}>OK</button>
          </div>
        </dialog>
      )}
    </>
  )
}
