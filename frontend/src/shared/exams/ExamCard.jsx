import { RiCalendarLine, RiEdit2Line, RiFolderOpenFill, RiGridLine, RiListCheck } from '@remixicon/react'

const FALLBACK_FOLDER_COLORS = [
  '#cf4564',
  '#397fd6',
  '#279b70',
  '#b77915',
  '#8855cd',
  '#b942a5',
  '#148e96',
  '#8190a5',
]

export function ExamFolder({ color = '#8190a5', size = 64 }) {
  return <RiFolderOpenFill className="exam-folder" size={size} style={{ color }} aria-hidden="true" />
}

export function ExamViewToggle({ value, onChange }) {
  return (
    <div className="exam-view-toggle" aria-label="Examination view">
      <button type="button" aria-label="Grid view" aria-pressed={value === 'grid'} onClick={() => onChange('grid')}><RiGridLine size={19} /></button>
      <button type="button" aria-label="List view" aria-pressed={value === 'list'} onClick={() => onChange('list')}><RiListCheck size={19} /></button>
    </div>
  )
}

export function ExamCard({ exam, onOpen, onEdit, cardAction, children }) {
  const dated = getDisplayDate(exam)
  const date = dated[1] ? new Date(dated[1]) : null
  const folderColor = exam.folderColor || stableFolderColor(exam.id || exam.title)

  return (
    <article className="exam-card" style={{ '--exam-folder-color': folderColor }}>
      <span className="exam-card__binding" aria-hidden="true">{Array.from({ length: 7 }, (_, index) => <i key={index} />)}</span>
      <button type="button" className="exam-card__open" aria-label={`Open ${exam.title}`} onClick={onOpen}>
        <ExamFolder color={folderColor} />
        <h2 title={exam.title}>{exam.title}</h2>
        <p title={`${exam.subjectName} · ${exam.assessmentName}`}>{exam.subjectName} <span>·</span> {exam.assessmentName}</p>
        <span className="exam-card__revision">Revision {exam.revisionNumber || 1}</span>
      </button>
      <div className="exam-card__menu">
        {exam.status === 'draft' && onEdit && <button type="button" className="exam-card__edit" aria-label={`Edit ${exam.title}`} title="Edit draft" onClick={onEdit}><RiEdit2Line size={17} /></button>}
        {children}
      </div>
      <span className={`exam-status exam-status--${exam.status}`}>{exam.statusLabel}</span>
      <div className="exam-card__date">
        <RiCalendarLine size={16} />
        {date && !Number.isNaN(date.getTime())
          ? `${dated[0]} ${date.toLocaleDateString(undefined, { day: 'numeric', month: 'short', year: 'numeric' })}`
          : 'Not scheduled'}
      </div>
      <div className="exam-card__footer">
        <span>{exam.questionCount} {exam.questionCount === 1 ? 'question' : 'questions'} <span>·</span> {exam.durationMinutes} min</span>
        {cardAction}
      </div>
    </article>
  )
}

function getDisplayDate(exam) {
  if (exam.status === 'closed' && exam.closedAt) return ['Closed', exam.closedAt]
  if (exam.status === 'cancelled' && exam.cancelledAt) return ['Cancelled', exam.cancelledAt]
  if (exam.status === 'active' && exam.activatedAt) return ['Activated', exam.activatedAt]
  if (exam.status === 'sealed' && exam.sealedAt) return ['Sealed', exam.sealedAt]
  if (exam.status === 'submitted' && exam.submittedAt) return ['Submitted', exam.submittedAt]
  if (exam.scheduledStartAt) return ['Scheduled', exam.scheduledStartAt]
  if (exam.status === 'draft') return ['Created', exam.createdAt]
  return ['Updated', exam.updatedAt]
}

function stableFolderColor(seed) {
  const value = String(seed || 'exam')
  let hash = 0
  for (let index = 0; index < value.length; index += 1) {
    hash = ((hash << 5) - hash + value.charCodeAt(index)) | 0
  }
  return FALLBACK_FOLDER_COLORS[Math.abs(hash) % FALLBACK_FOLDER_COLORS.length]
}
