import {
  currentExamRevisions,
  examRevisionHistory,
} from '../../shared/exams/examLineage'

const CURRENT_ROSTER_EXAM_STATES = new Set([
  'sealed',
  'active',
  'suspended',
  'closing',
  'cancelling',
])

const TERMINAL_EXAM_STATES = new Set(['closed', 'cancelled'])

function hasPreparedRoster(exam) {
  return exam?.rosterStatus && exam.rosterStatus !== 'not_prepared'
}

function revisionNumber(exam) {
  return Number(exam?.revisionNumber || 1)
}

function timeValue(value) {
  const parsed = value ? new Date(value).getTime() : 0
  return Number.isFinite(parsed) ? parsed : 0
}

function compareRevisionDesc(left, right) {
  const revisionDelta = revisionNumber(right) - revisionNumber(left)
  if (revisionDelta) return revisionDelta
  return timeValue(right.createdAt) - timeValue(left.createdAt)
}

export function buildRosterLineageIndex(exams = []) {
  const rows = Array.isArray(exams) ? exams : []
  const currentRows = currentExamRevisions(rows)
  const currentIds = new Set(currentRows.map((exam) => exam.id))
  const lineageByCurrentId = new Map()
  const currentIdByExamId = new Map()

  for (const current of currentRows) {
    const lineage = examRevisionHistory(rows, current)
    lineageByCurrentId.set(current.id, lineage)
    for (const exam of lineage) currentIdByExamId.set(exam.id, current.id)
  }

  return {
    currentRows,
    currentIds,
    lineageByCurrentId,
    currentIdFor: (exam) => currentIdByExamId.get(exam?.id) || exam?.id,
  }
}

export function isSupersededRevision(exam, exams = []) {
  if (!exam) return false
  const index = buildRosterLineageIndex(exams)
  return index.currentIdFor(exam) !== exam.id
}

export function rosterHistoryKind(exam, exams = []) {
  if (!exam || !hasPreparedRoster(exam)) return null
  if (isSupersededRevision(exam, exams)) return 'superseded'
  if (TERMINAL_EXAM_STATES.has(exam.status)) return exam.status
  return null
}

export function isHistoricalRoster(exam, exams = []) {
  return Boolean(rosterHistoryKind(exam, exams))
}

export function partitionRosterExams(exams = []) {
  const rows = Array.isArray(exams) ? exams : []
  const index = buildRosterLineageIndex(rows)

  const current = index.currentRows
    .filter(
      (exam) =>
        hasPreparedRoster(exam) && CURRENT_ROSTER_EXAM_STATES.has(exam.status),
    )
    .sort((left, right) => {
      const leftTime = timeValue(left.scheduledStartAt) || timeValue(left.createdAt)
      const rightTime = timeValue(right.scheduledStartAt) || timeValue(right.createdAt)
      return rightTime - leftTime
    })

  const historyGroups = index.currentRows
    .map((representative) => {
      const lineage = index.lineageByCurrentId.get(representative.id) || [representative]
      const entries = lineage
        .filter(hasPreparedRoster)
        .filter(
          (exam) =>
            exam.id !== representative.id || TERMINAL_EXAM_STATES.has(exam.status),
        )
        .sort(compareRevisionDesc)

      if (!entries.length) return null
      return {
        id: representative.id,
        title: representative.title || 'Examination roster',
        academicLevelName: representative.academicLevelName || '',
        subjectName: representative.subjectName || '',
        assessmentName: representative.assessmentName || '',
        latestRevisionNumber: revisionNumber(representative),
        entries,
      }
    })
    .filter(Boolean)
    .sort((left, right) => {
      const leftExam = left.entries[0]
      const rightExam = right.entries[0]
      const leftTime = timeValue(leftExam?.updatedAt) || timeValue(leftExam?.createdAt)
      const rightTime = timeValue(rightExam?.updatedAt) || timeValue(rightExam?.createdAt)
      return rightTime - leftTime
    })

  return { current, historyGroups }
}

export function rosterHistoryLabel(kind) {
  if (kind === 'superseded') return 'Superseded'
  if (kind === 'closed') return 'Closed'
  if (kind === 'cancelled') return 'Cancelled'
  return 'Historical'
}

export function rosterHistoryDescription(exam, exams = []) {
  const kind = rosterHistoryKind(exam, exams)
  if (kind === 'superseded') {
    return `Revision ${revisionNumber(exam)} was replaced by a later exam revision. Its roster is preserved for audit and is read-only.`
  }
  if (kind === 'closed') {
    return 'This examination is closed. Its final candidate roster is preserved for audit and remains available to review.'
  }
  if (kind === 'cancelled') {
    return 'This examination was cancelled. Its candidate roster is preserved as historical scheduling evidence.'
  }
  return ''
}
