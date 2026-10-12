import { useEffect, useMemo, useState } from 'react'
import { Notice, SelectControl } from '../ui'

export function LeadAuthorControl(props) {
  return <LeadAuthorContent key={`${props.subjectId || ''}:${props.termId || ''}`} {...props} />
}

function LeadAuthorContent({
  gateway,
  subjectId,
  termId,
  value,
  onChange,
  onResolvedName,
  disabled = false,
}) {
  const canLoad = Boolean(subjectId && termId && typeof gateway?.exams?.listLeadCandidates === 'function')
  const [candidates, setCandidates] = useState([])
  const [loading, setLoading] = useState(canLoad)
  const [error, setError] = useState(subjectId && termId && !canLoad ? 'Eligible teachers could not be loaded. Administrator coordination is still available.' : '')

  useEffect(() => {
    if (!canLoad) return undefined
    let cancelled = false

    gateway.exams.listLeadCandidates({ curriculum_subject_id: subjectId, term_id: termId })
      .then((rows) => {
        if (!cancelled) setCandidates(Array.isArray(rows) ? rows : [])
      })
      .catch(() => {
        if (!cancelled) setError('Eligible teachers could not be loaded. Administrator coordination is still available.')
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })

    return () => { cancelled = true }
  }, [canLoad, gateway, subjectId, termId])

  const options = useMemo(() => {
    const rows = [
      { value: '', label: 'Administrator coordinates' },
      ...candidates.map((teacher) => ({
        value: teacher.id,
        label: teacherName(teacher),
        description: teacher.staff_id || undefined,
      })),
    ]

    if (value && !candidates.some((teacher) => teacher.id === value)) {
      rows.push({ value, label: 'Currently assigned teacher' })
    }
    return rows
  }, [candidates, value])

  useEffect(() => {
    if (typeof onResolvedName !== 'function') return
    if (!value) {
      onResolvedName('Administrator')
      return
    }
    const selected = candidates.find((teacher) => teacher.id === value)
    onResolvedName(selected ? teacherName(selected) : 'Assigned teacher')
  }, [candidates, onResolvedName, value])

  return (
    <div className="teacher-exam-field">
      <span>Lead author <small>(optional)</small></span>
      <SelectControl
        label="Lead author"
        value={value}
        onChange={onChange}
        options={options}
        disabled={disabled || loading || !subjectId || !termId}
      />
      {loading && <small>Loading eligible teachers…</small>}
      {error && <Notice tone="warning">{error}</Notice>}
    </div>
  )
}

function teacherName(teacher) {
  return [teacher.first_name, teacher.last_name].filter(Boolean).join(' ') || teacher.staff_id || 'Teacher'
}
