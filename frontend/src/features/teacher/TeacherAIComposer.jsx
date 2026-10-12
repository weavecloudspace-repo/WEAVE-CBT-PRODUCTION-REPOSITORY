import { handlePromptKeyDown } from './teacherPromptEvents'
import './teacher-ai.css'
import { useEffect, useRef, useState } from 'react'
import { RiArrowDownSLine, RiCornerDownLeftLine, RiCloseLine, RiWallet3Line, RiFileList3Line } from '@remixicon/react'
import { WeaveMark } from '../../shared/ui'
import { TeacherGenerationOptions } from './TeacherGenerationOptions'
import { TeacherGenerationStatus } from './TeacherGenerationStatus'
import { TeacherAIQuota } from './TeacherAIQuota'
import { useTeacherAIController, useTeacherAIQuota } from './teacherAI'



export function TeacherAIComposer({ bank, state, dispatch, gateway, onClose }) {
  const controller = useTeacherAIController(gateway, state.session?.actor?.id)
  const isAdmin = state.session?.role === 'admin'
  const quota = useTeacherAIQuota(gateway.ai, { includeRequests: !isAdmin })
  const [prompt, setPrompt] = useState('')
  const [count, setCount] = useState(5)
  const [type, setType] = useState('single_choice')
  const [difficulty, setDifficulty] = useState('medium')
  const [visuals, setVisuals] = useState('text_only')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [drafts, setDrafts] = useState([])
  const [sentPrompt, setSentPrompt] = useState('')
  const mounted = useRef(false)
  const pending = useRef(false)
  const promptInput = useRef(null)
  const creditsDetails = useRef(null)
  useEffect(() => {
    const closeCredits = (event) => {
      const details = creditsDetails.current
      if (!details?.open) return
      if (event.type === 'keydown') {
        if (event.key !== 'Escape') return
        details.open = false
        details.querySelector('summary')?.focus()
      } else if (!details.contains(event.target)) {
        details.open = false
      }
    }
    document.addEventListener('pointerdown', closeCredits)
    document.addEventListener('keydown', closeCredits)
    return () => {
      document.removeEventListener('pointerdown', closeCredits)
      document.removeEventListener('keydown', closeCredits)
    }
  }, [])
  useEffect(() => {
    mounted.current = true
    return () => { mounted.current = false }
  }, [])
  useEffect(() => {
    let active = true
    controller?.listDrafts().then((items) => {
      if (active) setDrafts(items.filter((item) => item.bank_id === bank?.id).sort((a, b) => b.updated_at.localeCompare(a.updated_at)))
    }).catch(() => { if (active) setError('Browser draft storage is unavailable. Enable site storage to use AI generation.') })
    return () => { active = false }
  }, [controller, bank?.id])
  const openDraft = (id) => dispatch({ type: 'staff', patch: { section: 'review-ai-questions', selectedAIDraftId: id } })
  const generate = async (event) => {
    event.preventDefault()
    if (pending.current || !controller || !bank || !prompt.trim()) return
    const questionCount = Number(count)
    if (!Number.isInteger(questionCount) || questionCount < 1 || questionCount > 50) {
      setError('Enter a whole number of questions between 1 and 50.')
      return
    }
    pending.current = true
    setBusy(true)
    setError('')
    const submittedPrompt = prompt.trim()
    setSentPrompt(submittedPrompt)
    setPrompt('')
    try {
      const draft = await controller.generate(bank.id, {
        generation_prompt: submittedPrompt, question_count: questionCount,
        question_type_counts: type === 'mixed'
          ? { single_choice: Math.ceil(questionCount / 2), multiple_choice: Math.floor(questionCount / 2) }
          : { [type]: questionCount },
        difficulty, visual_mode: visuals,
      })
      if (mounted.current) openDraft(draft.draft_id)
    } catch (error) {
      if (mounted.current) {
        setError(error.userMessage || error.message || 'Generation could not be confirmed.')
        if (!error.operationId) setPrompt(submittedPrompt)
        if (error.operationId) {
          try {
            const draft = await controller.getDraft(error.operationId)
            if (draft && mounted.current) setDrafts((items) => [draft, ...items.filter((item) => item.draft_id !== draft.draft_id)])
          } catch { setError('Browser storage could not be read. Return to this bank to recover your draft before generating again.') }
        }
      }
    } finally {
      pending.current = false
      if (mounted.current) { setBusy(false); void quota.refresh() }
    }
  }
  const generationDisabled = busy
    || drafts.some((draft) => draft.status === 'generating')
    || !bank
    || !controller
    || !prompt.trim()
    || quota.loading
    || !quota.quota
    || quota.quota.total_available_credits === 0

  return <aside className="teacher-ai-composer" aria-label="Question generation">
    <header className="teacher-ai-composer__heading"><RiFileList3Line size={18} /><h2>Generate questions</h2>{onClose && <button type="button" className="teacher-ai-icon-button" aria-label="Close question generation" onClick={onClose}><RiCloseLine size={19} /></button>}</header>
    <div className="teacher-ai-bank"><span>Question bank</span><strong>{bank?.name || 'Choose a question bank in the editor'}</strong></div>
    <div className="teacher-ai-conversation" aria-live="polite">
      {!sentPrompt && !busy && !drafts.length && !error && <div className="teacher-ai-welcome" aria-hidden="true">
        <WeaveMark monochrome className="teacher-ai-watermark" />
      </div>}
      {sentPrompt && <p className="teacher-ai-message teacher-ai-message--user">{sentPrompt}</p>}
      {busy && <TeacherGenerationStatus title="Creating your questions" detail="Preparing questions and answer choices for your review." />}
      {drafts.length > 0 && <div className="teacher-ai-recovery"><strong>Continue where you left off</strong>{drafts.map((draft) => <button type="button" disabled={busy} key={draft.draft_id} onClick={() => openDraft(draft.draft_id)}><span>{draft.generation_request.generation_prompt}</span><small>{draft.status === 'generating' ? 'Recover generation' : draft.status === 'saving' ? 'Confirm save' : `Review ${draft.questions.length} questions`}</small></button>)}</div>}
      {error && <p className="teacher-ai-error" role="alert">{error}</p>}
    </div>
    <div className="teacher-ai-bottom">
    <form className="teacher-ai-prompt" onSubmit={generate}>
      <textarea ref={promptInput} aria-label="Describe questions to generate" placeholder="e.g. Questions on fractions using everyday situations…" value={prompt} maxLength={10000} required disabled={busy} onChange={(event) => setPrompt(event.target.value)} onKeyDown={(event) => handlePromptKeyDown(event, generationDisabled)} rows={3} />
      <div className="teacher-ai-prompt__actions"><TeacherGenerationOptions count={count} setCount={setCount} difficulty={difficulty} setDifficulty={setDifficulty} type={type} setType={setType} visuals={visuals} setVisuals={setVisuals} disabled={busy} onOpen={() => { if (creditsDetails.current) creditsDetails.current.open = false }} /><button className="teacher-ai-send" type="submit" aria-label="Generate questions" title={busy ? "Generating questions" : "Generate questions"} disabled={generationDisabled}><RiCornerDownLeftLine size={19} /></button></div>
    </form>
    <div className="teacher-ai-footer">
    <details ref={creditsDetails} className="teacher-ai-credit-details"><summary aria-label={quota.quota ? `${quota.quota.total_available_credits} AI credits available` : 'AI credit usage'}>
        <RiWallet3Line size={15} />
        <strong className="teacher-ai-credit-balance">{quota.quota ? quota.quota.total_available_credits : '\u2014'}</strong>
        <span>AI credits</span>
        <RiArrowDownSLine className="teacher-ai-disclosure" size={16} />
      </summary><TeacherAIQuota model={quota} api={gateway.ai} onManageCredits={isAdmin ? () => dispatch({ type: 'staff', patch: { section: 'ai-usage' } }) : undefined} /></details>
    <p className="teacher-ai-footnote">Check each answer before adding.</p>
    </div>
    </div>
  </aside>
}
