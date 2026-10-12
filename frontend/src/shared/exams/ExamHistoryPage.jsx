import { RiEdit2Line, RiHistoryLine } from '@remixicon/react'
import { ExamFolder } from './ExamCard'
import { examRevisionHistory } from './examLineage'
import { canManageExam } from './examPermissions'
import { useAuthoringResultReviews } from './useAuthoringResultReviews'
import { Icon } from '../icons/Icon'
import './exam-workspace.css'
import './exam-history.css'

export function ExamHistoryPage({ state, dispatch, teacherData, gateway }) {
  const selected = teacherData.exams.find((exam) => exam.id === state.staff.selectedExamId)
  const reviews = useAuthoringResultReviews(
    gateway,
    teacherData.exams,
    state.session?.actor?.role === 'admin',
  )
  const history = selected ? examRevisionHistory(teacherData.exams, selected) : []
  const current = history[0]
  const reviewByExamId = new Map(reviews.reviews.map((review) => [review.exam_id, review]))
  const currentDisposition = current ? reviewByExamId.get(current.id)?.result_disposition : null
  const currentEditable = current
    ? canManageExam(current, state.session?.actor, teacherData.assignments)
    : false

  const navigate = (section, id = null) => dispatch({
    type: 'staff',
    patch: { section, selectedExamId: id, examAuthoringNotice: '' },
  })

  return (
    <div className="teacher-reference-page exam-history-page">
      <header className="teacher-page-heading exam-history-heading">
        <div>
          <div className="teacher-page-title-line">
            <span className="teacher-page-title-icon"><Icon name="exam" size={26} /></span>
            <h1>Examination history</h1>
          </div>
          <p>Review the current paper and every revision preserved in this examination lineage.</p>
        </div>
        <button type="button" className="teacher-secondary-action" onClick={() => navigate('exams')}>
          <Icon name="back" size={17} /> Back to Examinations
        </button>
      </header>

      {teacherData.loading && !current ? (
        <p role="status">Loading examination history...</p>
      ) : !current ? (
        <p role="status">This examination is no longer available.</p>
      ) : (
        <>
          <section
            className="exam-history-overview"
            aria-label="Current examination"
            style={current.folderColor ? { '--exam-history-folder-color': current.folderColor } : undefined}
          >
            <div className="exam-history-overview__top">
              <div className="exam-history-overview__identity">
                <span className="exam-history-folder-wrap">
                  <ExamFolder color={current.folderColor || undefined} size={54} />
                </span>
                <div className="exam-history-overview__title">
                  <span className="exam-history-eyebrow">Current examination</span>
                  <h2>{current.title}</h2>
                  <div className="exam-history-context" aria-label="Academic context">
                    <span>{current.academicLevelName || 'Level'}</span>
                    <span>{current.subjectName || 'Subject'}</span>
                    <span>{current.assessmentName || 'Assessment'}</span>
                  </div>
                </div>
              </div>

              <div className="exam-history-overview__actions">
                <div className="exam-history-overview__badges">
                  <span className={`exam-status exam-status--${current.status}`}>{current.statusLabel}</span>
                  {currentDisposition && (
                    <span className={`exam-history-disposition exam-history-disposition--${currentDisposition}`}>
                      {label(currentDisposition)}
                    </span>
                  )}
                </div>
                <span className="exam-history-current-revision">Revision {current.revisionNumber || 1} · Current</span>
                {currentEditable && (
                  <button
                    type="button"
                    className="teacher-primary-action exam-history-edit-current"
                    onClick={() => navigate('create-exam', current.id)}
                  >
                    <RiEdit2Line size={16} /> Edit current draft
                  </button>
                )}
              </div>
            </div>

            <dl className="exam-history-overview__facts">
              <HistoryFact label="Level" value={current.academicLevelName || '—'} />
              <HistoryFact label="Subject" value={current.subjectName || '—'} />
              <HistoryFact label="Component" value={current.assessmentName || '—'} />
              <HistoryFact label="Questions" value={String(current.questionCount ?? '—')} />
              <HistoryFact label="Duration" value={`${current.durationMinutes || 0} minutes`} />
              <HistoryFact label="Created" {...dateFact(current.createdAt, 'Unavailable')} />
              <HistoryFact label="Scheduled" {...dateFact(current.scheduledStartAt, 'Not scheduled')} />
            </dl>
          </section>

          {reviews.error && <p className="exam-authoring-recovery" role="status">{reviews.error}</p>}

          <section className="exam-history-records" aria-labelledby="revision-history-title">
            <div className="exam-history-section-heading">
              <div className="exam-history-section-heading__title">
                <span><RiHistoryLine size={19} /></span>
                <div>
                  <h2 id="revision-history-title">Revision history</h2>
                  <p>Latest first. Earlier revisions remain read-only and preserved.</p>
                </div>
              </div>
              <span>{history.length} {history.length === 1 ? 'revision' : 'revisions'}</span>
            </div>

            <ol className="exam-history-timeline">
              {history.map((exam, index) => {
                const disposition = reviewByExamId.get(exam.id)?.result_disposition
                const created = dateFact(exam.createdAt, 'Unavailable')
                const scheduled = dateFact(exam.scheduledStartAt, 'Not scheduled')

                return (
                  <li key={exam.id} className={index === 0 ? 'is-current' : ''} aria-current={index === 0 ? 'true' : undefined}>
                    <span className="exam-history-marker" aria-hidden="true">{exam.revisionNumber || 1}</span>
                    <article className="exam-history-record">
                      <header>
                        <div>
                          <div className="exam-history-record__title">
                            <h3>Revision {exam.revisionNumber || 1}</h3>
                            {index === 0 && <span className="exam-history-current-tag">Current</span>}
                          </div>
                          <p>{exam.title}</p>
                        </div>
                        <div className="exam-history-record__badges">
                          <span className={`exam-status exam-status--${exam.status}`}>{exam.statusLabel}</span>
                          {disposition && (
                            <span className={`exam-history-disposition exam-history-disposition--${disposition}`}>
                              {label(disposition)}
                            </span>
                          )}
                        </div>
                      </header>

                      <dl className="exam-history-facts">
                        <HistoryFact label="Questions" value={String(exam.questionCount ?? '—')} />
                        <HistoryFact label="Duration" value={`${exam.durationMinutes || 0} minutes`} />
                        <HistoryFact label="Created" value={created.value} detail={created.detail} />
                        <HistoryFact label="Scheduled" value={scheduled.value} detail={scheduled.detail} />
                      </dl>

                      <footer>
                        <details>
                          <summary>View revision details</summary>
                          <dl className="exam-history-details">
                            <div><dt>Assessment</dt><dd>{exam.assessmentName}</dd></div>
                            <div><dt>Question selection</dt><dd>{label(exam.selectionMode)}</dd></div>
                            <div className="exam-history-details__wide"><dt>Instructions</dt><dd>{exam.instructions || 'No instructions added.'}</dd></div>
                            {exam.closedAt && <div><dt>Closed</dt><dd>{date(exam.closedAt)}</dd></div>}
                          </dl>
                        </details>
                      </footer>
                    </article>
                  </li>
                )
              })}
            </ol>
          </section>
        </>
      )}
    </div>
  )
}

function HistoryFact({ label: factLabel, value, detail }) {
  return (
    <div className="exam-history-fact">
      <dt>{factLabel}</dt>
      <dd>{value}{detail && <small>{detail}</small>}</dd>
    </div>
  )
}

function label(value) {
  return String(value || 'Not specified')
    .replaceAll('_', ' ')
    .replace(/\b\w/g, (letter) => letter.toUpperCase())
}

function dateFact(value, fallback) {
  if (!value) return { value: fallback, detail: '' }
  const parsed = new Date(value)
  if (Number.isNaN(parsed.getTime())) return { value: 'Unavailable', detail: '' }
  return {
    value: parsed.toLocaleDateString(undefined, { day: 'numeric', month: 'short', year: 'numeric' }),
    detail: parsed.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' }),
  }
}

function date(value) {
  if (!value) return 'Not scheduled'
  const parsed = new Date(value)
  return Number.isNaN(parsed.getTime())
    ? 'Unavailable'
    : parsed.toLocaleString(undefined, {
      day: 'numeric',
      month: 'short',
      year: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    })
}
