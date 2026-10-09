import { useEffect, useEffectEvent, useState } from 'react'
import { RiDeleteBinLine, RiSearchLine } from '@remixicon/react'
import { Notice } from '../ui'
import { FormattedText } from '../ui/FormattedText'

export function ManualQuestionPicker({
  bankId,
  exam,
  gateway,
  selectedIds,
  onChange,
  onPreview,
  disabled,
  onBusyChange,
  onSaved,
  actorId,
  canManageAllSelections = false,
  deferManagedSelections = false,
  ignorePersistedSelections = false,
  managedSelectionReady = false,
}) {
  const [resource, setResource] = useState({ loading: true, questions: [], selections: [], version: null, error: '' })
  const [query, setQuery] = useState('')
  const [selectedOnly, setSelectedOnly] = useState(false)
  const [busy, setBusy] = useState(false)
  const [retry, setRetry] = useState(0)
  const [stagedAddIds, setStagedAddIds] = useState([])
  const [managedIds, setManagedIds] = useState([])
  const examId = exam?.id
  const limit = Number(exam?.questionCount)
  const contributionMode = Boolean(examId && !canManageAllSelections)
  const managedDraftMode = Boolean(examId && canManageAllSelections && deferManagedSelections)
  const contributionStorageKey = contributionMode && actorId
    ? `weave-cbt:manual-contribution:${examId}:${actorId}:${bankId}`
    : ''

  const receiveManagedSelections = useEffectEvent((selections) => {
    const nextManagedIds = managedSelectionReady
      ? selectedIds
      : ignorePersistedSelections ? [] : selections.map((row) => row.question_id)
    setManagedIds(nextManagedIds)
    onChange?.(nextManagedIds)
  })

  useEffect(() => {
    let cancelled = false
    Promise.all([
      gateway.questions.listQuestionsForBank(bankId, { include_archived: Boolean(examId) }),
      examId ? gateway.exams.listManualQuestions(examId) : Promise.resolve([]),
      examId ? gateway.exams.getExam(examId) : Promise.resolve(null),
    ]).then(([questions, selections, current]) => {
      if (cancelled) return

      const persistedIds = new Set(selections.map((row) => row.question_id))
      const activeQuestionIds = new Set(questions.filter((question) => question.is_active).map((question) => question.id))
      const restored = contributionMode
        ? readStagedAdditions(contributionStorageKey).filter((questionId) => activeQuestionIds.has(questionId) && !persistedIds.has(questionId))
        : []

      setStagedAddIds(restored)
      persistStagedAdditions(contributionStorageKey, restored)

      if (managedDraftMode) {
        receiveManagedSelections(selections)
      }

      setResource({ loading: false, questions, selections, version: current?.authoring_version ?? current?.authoringVersion ?? null, error: '' })
    }).catch((error) => {
      if (!cancelled) setResource((previous) => ({ ...previous, loading: false, error: error.userMessage || 'Could not load the question bank. Please retry.' }))
    })
    return () => { cancelled = true }
  }, [bankId, contributionMode, contributionStorageKey, examId, gateway, ignorePersistedSelections, managedDraftMode, retry])

  const persistedIds = examId ? resource.selections.map((row) => row.question_id) : []
  const ids = examId
    ? managedDraftMode
      ? managedIds
      : contributionMode
        ? [...persistedIds, ...stagedAddIds.filter((questionId) => !persistedIds.includes(questionId))]
        : persistedIds
    : selectedIds
  const selected = new Set(ids)
  const staged = new Set(stagedAddIds)
  const selectionByQuestion = new Map(resource.selections.map((row) => [row.question_id, row]))
  const visible = resource.questions.filter((question) => (question.is_active || selected.has(question.id)) && (!selectedOnly || selected.has(question.id)) && question.prompt.toLowerCase().includes(query.trim().toLowerCase()))
  const stagedCount = stagedAddIds.length
  const selectionOverLimit = Number.isFinite(limit) && ids.length > limit

  const canRemoveSelectedQuestion = (questionId) => {
    if (!examId || canManageAllSelections || staged.has(questionId)) return true
    const selection = selectionByQuestion.get(questionId)
    return Boolean(actorId && selection?.added_by_actor_id && String(selection.added_by_actor_id) === String(actorId))
  }

  const stageAdditions = (nextIds) => {
    setStagedAddIds(nextIds)
    persistStagedAdditions(contributionStorageKey, nextIds)
  }

  const toggle = async (questionId) => {
    if (disabled || busy) return
    if (selected.has(questionId) && !canRemoveSelectedQuestion(questionId)) return
    if (!examId) {
      onChange(selected.has(questionId) ? ids.filter((id) => id !== questionId) : [...ids, questionId])
      return
    }

    if (managedDraftMode) {
      const nextIds = selected.has(questionId)
        ? ids.filter((id) => id !== questionId)
        : [...ids, questionId]
      setManagedIds(nextIds)
      onChange?.(nextIds)
      return
    }

    if (contributionMode && staged.has(questionId)) {
      stageAdditions(stagedAddIds.filter((id) => id !== questionId))
      return
    }

    if (contributionMode && !selected.has(questionId)) {
      stageAdditions([...stagedAddIds, questionId])
      return
    }

    setBusy(true)
    onBusyChange?.(true)
    try {
      const removing = selected.has(questionId)
      const updated = removing
        ? await gateway.exams.removeManualQuestion(examId, questionId, resource.version)
        : await gateway.exams.addManualQuestions(examId, [questionId], resource.version)
      // Legacy/immediate management paths and persisted contributor removals commit here.
      setResource((previous) => ({
        ...previous,
        version: updated.authoring_version ?? updated.authoringVersion ?? previous.version,
        error: '',
        selections: removing
          ? previous.selections.filter((row) => row.question_id !== questionId)
          : [...previous.selections, { question_id: questionId, added_by_actor_id: actorId }],
      }))
      await onSaved?.()
    } catch (error) {
      setResource((previous) => ({ ...previous, error: error.userMessage || 'Could not update the selection. Reload the questions before trying again.' }))
    } finally {
      setBusy(false)
      onBusyChange?.(false)
    }
  }

  const saveContribution = async () => {
    if (!contributionMode || disabled || busy || resource.loading || resource.error || !stagedCount || selectionOverLimit) return
    setBusy(true)
    onBusyChange?.(true)
    try {
      const expectedVersion = resource.version ?? exam?.authoringVersion ?? exam?.authoring_version ?? 1
      const updated = await gateway.exams.addManualQuestions(examId, stagedAddIds, expectedVersion)
      const committedIds = [...stagedAddIds]
      setResource((previous) => ({
        ...previous,
        version: updated.authoring_version ?? updated.authoringVersion ?? previous.version,
        error: '',
        selections: [
          ...previous.selections,
          ...committedIds.map((questionId) => ({ question_id: questionId, added_by_actor_id: actorId })),
        ],
      }))
      stageAdditions([])
      await onSaved?.()
    } catch (error) {
      setResource((previous) => ({
        ...previous,
        error: error.userMessage || 'Could not save your contribution. Your staged questions are still on this device; reload the questions and try again.',
      }))
    } finally {
      setBusy(false)
      onBusyChange?.(false)
    }
  }

  return (
    <div className="exam-manual-picker" aria-busy={resource.loading || busy}>
      <div className="exam-manual-picker__heading"><div><h3>Choose questions</h3><p>{examId
        ? managedDraftMode
          ? 'Selection changes stay in this form and are saved together with the examination.'
          : contributionMode
            ? 'New picks are kept on this device until you save your contribution. Removing one of your already-saved questions is applied immediately.'
            : 'Changes to this selection are saved immediately.'
        : 'Your selected questions will be added when you create the draft.'}</p></div><strong>{ids.length} / {limit} selected</strong></div>
      <div className="exam-manual-picker__tools">
        <label className="teacher-search-control"><RiSearchLine size={17} /><input aria-label="Search bank questions" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search this question bank" /></label>
        <button type="button" className="exam-text-action" aria-pressed={selectedOnly} onClick={() => setSelectedOnly(!selectedOnly)}>{selectedOnly ? 'Show all' : 'Selected only'}</button>
      </div>
      {resource.error && <div className="exam-manual-picker__error"><Notice tone="danger">{resource.error}</Notice> <button type="button" className="exam-text-action" disabled={busy} onClick={() => { setResource((previous) => ({ ...previous, loading: true, error: '' })); setRetry((value) => value + 1) }}>Reload questions</button></div>}
      {resource.loading ? <p role="status">Loading bank questions…</p> : <div className="exam-manual-picker__list">
        {visible.map((question) => {
          const selectionLocked = selected.has(question.id) && !canRemoveSelectedQuestion(question.id)
          return <div key={question.id} className={`exam-manual-question${selected.has(question.id) ? ' is-selected' : ''}`}>
            <div className="exam-manual-question__heading">
              <div className="exam-manual-question__content">
                {selected.has(question.id) && !selectionLocked ? (
                  <button type="button" className="exam-manual-question__remove" aria-label={`Remove question from exam: ${question.prompt}`} title="Remove from this exam" disabled={disabled || busy || Boolean(resource.error)} onClick={() => toggle(question.id)}><RiDeleteBinLine size={16} aria-hidden="true" /></button>
                ) : (
                  <input type="checkbox" aria-label={selectionLocked ? `Selected by another contributor: ${question.prompt}` : `Select question: ${question.prompt}`} title={selectionLocked ? 'Only the contributor, lead author or admin can remove this selection.' : 'Add to this exam'} checked={selected.has(question.id)} disabled={disabled || busy || Boolean(resource.error) || selectionLocked || (!question.is_active || ids.length >= limit)} onChange={() => toggle(question.id)} />
                )}
                <div><FormattedText text={question.prompt} /><small>{question.question_type.replaceAll('_', ' ')}{!question.is_active ? ' · Archived — remove before submission' : ''}{staged.has(question.id) ? ' · Not saved yet' : ''}</small></div>
              </div>
              <span className="exam-manual-question__author">{question.author_name || 'Unknown author'}</span>
            </div>
            <button type="button" className="exam-text-action exam-manual-question__preview" disabled={busy || !onPreview} onClick={(event) => onPreview(question.id, event.currentTarget)} aria-label={`Preview question: ${question.prompt}`}>Preview question</button>
          </div>
        })}
        {!visible.length && <p>{resource.questions.length ? 'No questions match this view.' : 'This bank has no available questions.'}</p>}
      </div>}
      {contributionMode && (
        <div className="exam-manual-picker__tools">
          <p role="status">{stagedCount
            ? `${stagedCount} question${stagedCount === 1 ? '' : 's'} waiting to be saved.`
            : 'No unsaved question additions.'}</p>
          <button type="button" className="teacher-primary-action" disabled={disabled || busy || Boolean(resource.error) || !stagedCount || selectionOverLimit} onClick={saveContribution}>
            {busy ? 'Saving contribution...' : 'Save contribution'}
          </button>
        </div>
      )}
      <p className="exam-section-note">Select {limit} questions before submitting the paper for review. {selectionOverLimit ? 'Remove the extra selections to match the question count.' : ''}</p>
    </div>
  )
}

function readStagedAdditions(storageKey) {
  if (!storageKey || typeof window === 'undefined') return []
  try {
    const parsed = JSON.parse(window.localStorage.getItem(storageKey) || '{}')
    return Array.isArray(parsed.questionIds) ? [...new Set(parsed.questionIds.filter(Boolean).map(String))] : []
  } catch {
    return []
  }
}

function persistStagedAdditions(storageKey, questionIds) {
  if (!storageKey || typeof window === 'undefined') return
  try {
    if (questionIds.length) {
      window.localStorage.setItem(storageKey, JSON.stringify({ questionIds }))
    } else {
      window.localStorage.removeItem(storageKey)
    }
  } catch {
    // Local storage is only a resilience layer. The in-memory draft still works for this page visit.
  }
}
