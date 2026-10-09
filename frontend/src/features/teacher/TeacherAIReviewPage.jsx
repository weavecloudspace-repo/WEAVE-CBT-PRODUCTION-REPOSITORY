import { scrollRegenerationFormIntoView } from './teacherReviewScroll'
import { useEffect, useRef, useState } from 'react'
import { RiArrowLeftLine, RiArrowRightLine, RiEyeLine, RiCheckLine, RiDeleteBin6Line, RiEdit2Line, RiRefreshLine, RiFileList3Line } from '@remixicon/react'
import { FormattedText } from '../../shared/ui/FormattedText'
import { TeacherGenerationStatus } from './TeacherGenerationStatus'
import { QuestionPreview } from './QuestionBuilder'
import { useTeacherAIController, useTeacherAIQuota, validateAIQuestion } from './teacherAI'
import './teacher-ai.css'



export function TeacherAIReviewPage({ state, dispatch, teacherData, gateway }) {
  const controller = useTeacherAIController(gateway, state.session?.actor?.id)
  const quota = useTeacherAIQuota(gateway.ai, { includeRequests: false })
  const draftId = state.staff.selectedAIDraftId
  const [draft, setDraft] = useState(null)
  const [activeIndex, setActiveIndex] = useState(0)
  const [previewOpen, setPreviewOpen] = useState(false)
  const questionHeading = useRef(null)
  const regenerationForm = useRef(null)
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState('')
  const [error, setError] = useState('')
  const [editing, setEditing] = useState(null)
  const [regenerating, setRegenerating] = useState(null)
  const [feedback, setFeedback] = useState('')
  const [deleting, setDeleting] = useState(null)
  const [discarding, setDiscarding] = useState(false)
  const pending = useRef(false)
  const currentIndex = Math.min(activeIndex, Math.max(0, (draft?.questions.length || 0) - 1))
  useEffect(() => {
    questionHeading.current?.focus()
  }, [currentIndex, previewOpen])
  useEffect(() => {
    if (regenerating === null) return undefined
    const frame = window.requestAnimationFrame(() => scrollRegenerationFormIntoView(regenerationForm.current))
    return () => window.cancelAnimationFrame(frame)
  }, [regenerating])
  useEffect(() => {
    let active = true
    if (!controller) return undefined
    controller.getDraft(draftId).then((item) => {
      if (active) { setDraft(item || null); setActiveIndex(0); setPreviewOpen(false); setLoading(false) }
    }).catch(() => { if (active) { setError('Unable to open browser draft storage.'); setLoading(false) } })
    return () => { active = false }
  }, [controller, draftId])
  const back = () => dispatch({ type: 'staff', patch: { section: 'create-question', selectedBankId: draft?.bank_id || state.staff.selectedBankId, selectedAIDraftId: null } })
  const run = async (label, action) => {
    if (pending.current) return
    pending.current = true
    setBusy(label)
    setError('')
    try { await action() } catch (error) {
      setError(error.userMessage || error.message || 'The action could not be completed. Your draft is kept on this browser.')
      try { setDraft(await controller.getDraft(draftId)) } catch { /* Retain the current preview. */ }
    } finally {
      pending.current = false
      setBusy('')
      void quota.refresh()
    }
  }
  const update = (questions) => run('Updating draft', async () => {
    setDraft(await controller.updateDraftQuestions(draftId, questions))
    setActiveIndex((index) => Math.min(index, Math.max(0, questions.length - 1)))
    setEditing(null)
    setDeleting(null)
  })
  const regenerate = (index) => run('Regenerating question', async () => {
    const { generation_prompt, difficulty, visual_mode, context } = draft.generation_request
    setDraft(await controller.regenerateDraft(draftId, index, { generation_prompt, difficulty, visual_mode, ...(context ? { context } : {}), instruction: feedback.trim() }))
    setRegenerating(null)
    setFeedback('')
  })
  const save = () => run('Adding questions', async () => {
    await controller.save(draftId)
    await teacherData.refresh()
    dispatch({ type: 'staff', patch: { section: 'bank-detail', selectedBankId: draft.bank_id, selectedAIDraftId: null } })
  })
  const bank = teacherData.banks.find((item) => item.id === draft?.bank_id)
  const locked = Boolean(busy || draft?.pending_regeneration || draft?.status === 'saving')
  const invalid = draft?.questions?.some((question) => validateAIQuestion(question))
  const currentQuestion = draft?.questions[currentIndex]
  const navigateQuestion = (offset) => {
    setActiveIndex(currentIndex + offset)
    setRegenerating(null)
    setFeedback('')
    setDeleting(null)
  }
  if (previewOpen && currentQuestion) return <div className="question-builder-page question-preview-page">
    <header className="question-preview-page__header">
      <div><h1>Question preview</h1><p>Question {currentIndex + 1} of {draft.questions.length} &middot; Student view</p></div>
      <button className="question-preview-back" type="button" onClick={() => setPreviewOpen(false)}><RiArrowLeftLine size={19} /> Back to review</button>
    </header>
    <QuestionPreview gateway={gateway} selectedBank={bank} questionType={currentQuestion.question_type} prompt={currentQuestion.prompt} instruction={currentQuestion.instruction || ''} questionImageSrc={draftImageSource(currentQuestion.image)} previewLabel="Draft preview" options={currentQuestion.options.map((option, index) => ({ clientId: `draft-option-${index}`, text: option.text || '', imageSrc: draftImageSource(option.image) }))} />
  </div>
  return <div className="teacher-ai-review">
    <header className="teacher-ai-review__header"><div><button className="question-builder-back" type="button" disabled={Boolean(busy)} onClick={back}><RiArrowLeftLine size={17} /> Question editor</button><h1>Review questions</h1><p>{bank?.name || 'Question bank'} <span aria-hidden="true">&middot;</span> Review each question before adding the batch.</p></div><button type="button" className="teacher-primary-action" disabled={!draft?.questions.length || Boolean(busy) || Boolean(draft?.pending_regeneration) || draft?.status === 'generating' || editing !== null || Boolean(invalid) || !bank} onClick={save}><RiCheckLine size={19} /> {busy === 'Adding questions' ? 'Adding…' : draft?.status === 'saving' ? 'Retry Add all' : `Add all${draft?.questions.length ? ` (${draft.questions.length})` : ''}`}</button></header>
    {error && <p className="teacher-ai-error" role="alert">{error}</p>}
    {loading ? <p role="status">Opening your draft…</p> : !draft ? <div className="teacher-ai-empty"><h2>Draft not available</h2><p>This draft may already have been added, or belongs to another browser or account.</p></div> : <div className="teacher-ai-review__grid">
      <section className="teacher-ai-review__list" aria-label="Generated questions" aria-busy={Boolean(busy)}>
        {currentQuestion && <nav className="teacher-ai-review__navigation" aria-label="Question navigation">
          <div className="teacher-ai-review__position" aria-live="polite">Question <strong>{currentIndex + 1}</strong> of {draft.questions.length}</div>
          <div className="teacher-ai-review__navigation-actions">
            <button className="teacher-secondary-action" type="button" disabled={locked || editing !== null || regenerating !== null} onClick={() => setPreviewOpen(true)}><RiEyeLine size={18} /> Preview</button>
            <button className="teacher-secondary-action" type="button" disabled={currentIndex === 0 || locked || editing !== null || regenerating !== null} onClick={() => navigateQuestion(-1)}><RiArrowLeftLine size={18} /> Back</button>
            <button className="teacher-secondary-action" type="button" disabled={currentIndex >= draft.questions.length - 1 || locked || editing !== null || regenerating !== null} onClick={() => navigateQuestion(1)}>Next <RiArrowRightLine size={18} /></button>
          </div>
        </nav>}

        {draft.status === 'generating' && <div className="teacher-ai-empty"><RiFileList3Line size={32} /><h2>Recover your generation</h2><p>The last response wasn’t received. Retry the same request to recover it safely.</p><button type="button" className="teacher-primary-action" disabled={Boolean(busy)} onClick={() => run('Recovering generation', async () => setDraft(await controller.retryGeneration(draftId)))}>Retry generation</button></div>}
        {draft.status === 'saving' && <p className="teacher-ai-message" role="status">The last save is awaiting confirmation. Questions are locked so “Retry Add all” can safely confirm the same batch.</p>}
        {draft.pending_regeneration && <div className="teacher-ai-message" role="status"><p>A regeneration is awaiting confirmation. Recover it before editing or adding this batch.</p><button type="button" className="teacher-secondary-action" disabled={Boolean(busy)} onClick={() => run('Recovering regeneration', async () => { setDraft(await controller.retryDraftRegeneration(draftId)); setRegenerating(null) })}>Retry regeneration</button></div>}
        {busy && <TeacherGenerationStatus title={busy} />}
        {draft.status === 'review' && !draft.questions.length && <div className="teacher-ai-empty"><h2>No questions left in this draft</h2><p>Return to the editor to generate another set.</p></div>}
        {draft.questions.slice(currentIndex, currentIndex + 1).map((question) => { const index = currentIndex; return <article className="teacher-ai-question" key={index}>
          <header><span className="teacher-ai-question__number">{String(index + 1).padStart(2, '0')}</span><span className="teacher-ai-question__type">{question.question_type === 'single_choice' ? 'Single choice' : 'Multiple choice'}</span><div className="teacher-ai-question__actions"><button type="button" aria-label={`Edit question ${index + 1}`} disabled={locked || editing !== null} onClick={() => { setEditing(index); setRegenerating(null); setDeleting(null) }}><RiEdit2Line size={17} /> Edit</button><button type="button" aria-label={`Regenerate question ${index + 1}`} disabled={locked || editing !== null} aria-expanded={regenerating === index} onClick={() => { setRegenerating((current) => current === index ? null : index); setFeedback(''); setDeleting(null) }}><RiRefreshLine size={17} /> Regenerate</button><button type="button" aria-label={`Delete question ${index + 1}`} disabled={locked || editing !== null} onClick={() => setDeleting(index)}><RiDeleteBin6Line size={17} /></button></div></header>
          {editing === index ? <DraftEditor question={question} index={index} disabled={locked} onCancel={() => setEditing(null)} onSave={(updated) => update(draft.questions.map((item, position) => position === index ? updated : item))} /> : <>
            {question.instruction && <p className="teacher-ai-question__instruction"><FormattedText text={question.instruction} /></p>}
            <h2 ref={questionHeading} tabIndex={-1}><FormattedText text={question.prompt} /></h2><DraftImage image={question.image} />
            <ol className="teacher-ai-answers">{question.options.map((option, position) => <li key={position} className={option.is_correct ? 'is-correct' : ''}><span>{String.fromCharCode(65 + position)}</span><div><FormattedText text={option.text || ''} /><DraftImage image={option.image} /></div>{option.is_correct && <span className="teacher-ai-answer-correct"><RiCheckLine size={16} /> Correct</span>}</li>)}</ol>
          </>}
          {deleting === index && <div className="teacher-ai-inline-confirm"><p>Remove this question from the draft?</p><button className="teacher-secondary-action" type="button" disabled={locked} onClick={() => setDeleting(null)}>Keep question</button><button className="teacher-secondary-action" type="button" disabled={locked} onClick={() => update(draft.questions.filter((_, position) => position !== index))}>Remove question</button></div>}
          {regenerating === index && !draft.pending_regeneration && <form ref={regenerationForm} className="teacher-ai-refine" onSubmit={(event) => { event.preventDefault(); void regenerate(index) }}><label>What should change?<textarea value={feedback} required maxLength={10000} disabled={locked} onChange={(event) => setFeedback(event.target.value)} placeholder="e.g. Use a real-life example and make the distractors less obvious." /></label>{quota.error && <p role="alert">{quota.error} <button className="text-button" type="button" disabled={quota.loading} onClick={() => void quota.refresh()}>Retry credit check</button></p>}
            {!quota.loading && quota.quota?.total_available_credits === 0 && <p role="status">No credits available for regeneration.</p>}
            <div><small>{quota.loading ? 'Checking available credits...' : 'Regeneration uses AI credits.'}</small><button className="text-button" type="button" disabled={locked} onClick={() => setRegenerating(null)}>Cancel</button><button className="teacher-primary-action" type="submit" disabled={locked || !feedback.trim() || quota.loading || !quota.quota?.total_available_credits}>Regenerate</button></div></form>}
        </article>})}
      </section>
      <footer className="teacher-ai-review__footer"><p>Draft changes stay on this browser until you add the questions.</p>{!bank && !teacherData.loading && <p role="alert">This bank is no longer available in your teaching scope.</p>}{draft.status !== 'saving' && <div className="teacher-ai-discard">{discarding ? <><p>Discard this draft? Used credits are not refunded.</p><button type="button" className="text-button" disabled={Boolean(busy)} onClick={() => setDiscarding(false)}>Keep draft</button><button type="button" className="text-button" disabled={Boolean(busy)} onClick={() => run('Discarding draft', async () => { await controller.discardDraft(draftId); back() })}>Confirm discard</button></> : <button type="button" className="text-button" disabled={Boolean(busy)} onClick={() => setDiscarding(true)}>Discard draft</button>}</div>}</footer>
    </div>}
  </div>
}

function draftImageSource(image) {
  return image && ['image/png', 'image/jpeg', 'image/webp'].includes(image.content_type)
    ? `data:${image.content_type};base64,${image.data_base64}` : null
}

function DraftImage({ image }) {
  if (!image || !['image/png', 'image/jpeg', 'image/webp'].includes(image.content_type)) return null
  return <figure className="teacher-ai-image"><img src={`data:${image.content_type};base64,${image.data_base64}`} alt={image.alt_text || 'Question illustration'} />{(image.attribution_text || image.creator || image.license_name) && <figcaption>{[image.attribution_text || image.creator, image.license_name].filter(Boolean).join(' · ')}</figcaption>}</figure>
}

function DraftEditor({ question, index, disabled, onCancel, onSave }) {
  const [value, setValue] = useState(() => structuredClone(question))
  const issue = validateAIQuestion(value)
  const changeOption = (position, patch) => setValue((current) => ({ ...current, options: current.options.map((option, i) => i === position ? { ...option, ...patch } : option) }))
  return <form className="teacher-ai-editor" onSubmit={(event) => { event.preventDefault(); if (!issue) onSave(value) }}><fieldset disabled={disabled}>
    <label>Question prompt<textarea required maxLength={20000} value={value.prompt} onChange={(event) => setValue({ ...value, prompt: event.target.value })} /></label>
    <label>Instruction<textarea maxLength={10000} value={value.instruction || ''} onChange={(event) => setValue({ ...value, instruction: event.target.value || null })} /></label>
    <DraftImage image={value.image} />{value.image && <button type="button" className="text-button" onClick={() => setValue({ ...value, image: null })}>Remove question image</button>}
    <p>Mark the correct answer{value.question_type === 'multiple_choice' ? 's' : ''}.</p>
    {value.options.map((option, position) => <div className="teacher-ai-edit-option" key={position}><div><input type={value.question_type === 'single_choice' ? 'radio' : 'checkbox'} name={`correct-${index}`} aria-label={`Option ${position + 1} is correct`} checked={option.is_correct} onChange={(event) => setValue({ ...value, options: value.options.map((item, i) => ({ ...item, is_correct: value.question_type === 'single_choice' ? i === position : i === position ? event.target.checked : item.is_correct })) })} /><input aria-label={`Option ${position + 1} text`} maxLength={10000} value={option.text || ''} onChange={(event) => changeOption(position, { text: event.target.value || null })} /><button type="button" className="teacher-ai-icon-button" aria-label={`Remove option ${position + 1}`} disabled={value.options.length <= 2} onClick={() => setValue({ ...value, options: value.options.filter((_, i) => i !== position) })}><RiDeleteBin6Line size={17} /></button></div><DraftImage image={option.image} />{option.image && <button type="button" className="text-button" onClick={() => changeOption(position, { image: null })}>Remove option image</button>}</div>)}
    <button type="button" className="text-button" disabled={value.options.length >= 50} onClick={() => setValue({ ...value, options: [...value.options, { text: '', image: null, is_correct: false }] })}>Add answer option</button>
    {issue && <p className="teacher-ai-error">{issue}</p>}<div className="teacher-ai-editor__actions"><button type="button" className="teacher-secondary-action" onClick={onCancel}>Cancel edit</button><button type="submit" className="teacher-primary-action" disabled={Boolean(issue)}>Keep changes</button></div>
  </fieldset></form>
}
