import { useEffect, useId, useRef } from 'react'
import { RiPauseCircleLine } from '@remixicon/react'
import './student.css'

export function StudentSuspensionNotice({ notice, onDismiss }) {
  const dialog = useRef(null)
  const titleId = useId()
  const descriptionId = useId()
  useEffect(() => {
    if (notice && !dialog.current.open) dialog.current.showModal()
    if (!notice && dialog.current.open) dialog.current.close()
  }, [notice])
  return <dialog ref={dialog} className="student-suspension-dialog" aria-labelledby={titleId} aria-describedby={descriptionId} onCancel={(event) => { event.preventDefault(); onDismiss() }}>
    {notice && <>
      <span className="student-suspension-dialog__icon"><RiPauseCircleLine size={32} aria-hidden="true" /></span>
      <h2 id={titleId}>Exam currently suspended</h2>
      <p id={descriptionId}>{notice.message || 'Your examination has been paused by the school. Your saved answers are protected. Stay in the waiting room until the exam resumes.'}</p>
      <p>Your session is still active. You do not need to sign in again.</p>
      <button type="button" className="premium-btn-primary" onClick={onDismiss}>Understood</button>
    </>}
  </dialog>
}