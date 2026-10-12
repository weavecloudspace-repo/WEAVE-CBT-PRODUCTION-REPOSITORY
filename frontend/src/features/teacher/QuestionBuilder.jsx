import { useEffect, useMemo, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { RiAddLine, RiArrowLeftLine, RiBold, RiDeleteBin6Line, RiEyeLine, RiImageAddLine, RiImageLine, RiItalic, RiLink, RiListOrdered, RiListUnordered, RiSave3Line, RiSuperscript2, RiUnderline } from '@remixicon/react'
import { buildAcademicLevels, findSubjectScope, humanizeAcademicCategory, listBanksForSubject, listSubjectsForLevel } from '../../shared/academics/authoringScope'
import { Notice, SelectControl, StatusBadge } from '../../shared/ui'
import { FormattedText } from '../../shared/ui/FormattedText'
import '../student/student.css'
import './question-builder.css'
import { TeacherAIComposer } from './TeacherAIComposer'
import { QuestionAuthoringWorkspace } from './QuestionAuthoringWorkspace'
import { QuestionAuthoringToolbar } from './QuestionAuthoringToolbar'

const MAX_IMAGE_SIZE = 5 * 1024 * 1024
const IMAGE_TYPES = new Set(['image/jpeg', 'image/png', 'image/webp'])

function makeOption(seed = {}) {
  return {
    clientId: seed.clientId || `${Date.now()}-${Math.random().toString(36).slice(2)}`,
    id: seed.id || null,
    text: seed.text || '',
    isCorrect: Boolean(seed.is_correct ?? seed.isCorrect),
    imageAssetId: seed.image_asset_id || seed.imageAssetId || null,
    imageFile: null,
    removeExistingImage: false,
  }
}

function initialOptions() {
  return [makeOption(), makeOption(), makeOption(), makeOption()]
}

export function QuestionBuilder({ enableAI = false, mode = 'create', state, dispatch, teacherData, gateway }) {
  const editing = mode === 'edit'
  const [aiOpen, setAIOpen] = useState(false)
  const questionId = state.staff.selectedQuestionId
  const initializedQuestionRef = useRef(null)
  const promptRef = useRef(null)
  const instructionRef = useRef(null)
  const instructionTriggerRef = useRef(null)
  const initialBank = teacherData.banks.find((bank) => bank.id === state.staff.selectedBankId) || teacherData.banks[0] || null
  const initialSubject = findSubjectScope(teacherData.subjects, initialBank?.curriculumSubjectId) || teacherData.subjects[0] || null
  const [levelId, setLevelId] = useState(initialSubject?.academicLevelId || initialBank?.academicLevelId || '')
  const [subjectId, setSubjectId] = useState(initialBank?.curriculumSubjectId || initialSubject?.id || '')
  const [bankId, setBankId] = useState(initialBank?.id || '')
  const [questionType, setQuestionType] = useState('single_choice')
  const [prompt, setPrompt] = useState('')
  const [instruction, setInstruction] = useState('')
  const [questionImageAssetId, setQuestionImageAssetId] = useState(null)
  const [questionImageFile, setQuestionImageFile] = useState(null)
  const [removeQuestionImage, setRemoveQuestionImage] = useState(false)
  const [options, setOptions] = useState(initialOptions)
  const [loading, setLoading] = useState(editing)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const [previewOpen, setPreviewOpen] = useState(false)
  const [instructionModalOpen, setInstructionModalOpen] = useState(false)
  const [instructionDraft, setInstructionDraft] = useState('')

  useEffect(() => {
    window.scrollTo({ top: 0, behavior: 'auto' })
  }, [previewOpen])

  useEffect(() => {
    if (!instructionModalOpen) return undefined
    const previousOverflow = document.body.style.overflow
    const onKeyDown = (event) => {
      if (event.key === 'Escape') {
        setInstructionModalOpen(false)
        window.requestAnimationFrame(() => instructionTriggerRef.current?.focus())
      }
    }
    document.body.style.overflow = 'hidden'
    document.addEventListener('keydown', onKeyDown)
    window.requestAnimationFrame(() => instructionRef.current?.focus())
    return () => {
      document.body.style.overflow = previousOverflow
      document.removeEventListener('keydown', onKeyDown)
    }
  }, [instructionModalOpen])

  useEffect(() => {
    if (!editing || !questionId || initializedQuestionRef.current === questionId) return undefined
    let cancelled = false
    setLoading(true)
    setError('')
    gateway.questions.getQuestion(questionId)
      .then((question) => {
        if (cancelled) return
        initializedQuestionRef.current = questionId
        const nextBank = teacherData.banks.find((bank) => bank.id === question.bank_id)
        const nextSubject = findSubjectScope(teacherData.subjects, nextBank?.curriculumSubjectId)
        setLevelId(nextSubject?.academicLevelId || nextBank?.academicLevelId || '')
        setSubjectId(nextBank?.curriculumSubjectId || nextSubject?.id || '')
        setBankId(question.bank_id)
        setQuestionType(question.question_type)
        setPrompt(question.prompt || '')
        setInstruction(question.instruction || '')
        setQuestionImageAssetId(question.image_asset_id || null)
        setQuestionImageFile(null)
        setRemoveQuestionImage(false)
        setOptions((question.options || []).map((option) => makeOption(option)))
      })
      .catch((requestError) => {
        if (!cancelled) setError(requestError.userMessage || 'Weave could not load this question for editing.')
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => { cancelled = true }
  }, [editing, gateway, questionId, teacherData.banks, teacherData.subjects])

  const levels = useMemo(() => buildAcademicLevels(teacherData.subjects), [teacherData.subjects])
  const subjectsForLevel = useMemo(
    () => listSubjectsForLevel(teacherData.subjects, levelId),
    [levelId, teacherData.subjects],
  )
  const subjectBanks = useMemo(
    () => listBanksForSubject(teacherData.banks, subjectId),
    [subjectId, teacherData.banks],
  )
  const resolvedBankId = bankId || subjectBanks[0]?.id || ''
  const selectedSubject = findSubjectScope(teacherData.subjects, subjectId)
  const selectedBank = subjectBanks.find((bank) => bank.id === resolvedBankId)
  const levelOptions = levels.map((level) => ({
    value: level.id,
    label: level.name,
    description: humanizeAcademicCategory(level.category) || undefined,
  }))
  const subjectOptions = subjectsForLevel.map((subject) => ({
    value: subject.id,
    label: subject.name,
    description: subject.code || undefined,
  }))
  const bankOptions = subjectBanks.map((bank) => ({
    value: bank.id,
    label: bank.name,
    description: `${bank.count || 0} questions`,
  }))
  const correctCount = options.filter((option) => option.isCorrect).length
  const validation = useMemo(() => validateDraft({ prompt, questionType, options }), [options, prompt, questionType])
  const hasQuestionImage = Boolean(questionImageFile || (questionImageAssetId && !removeQuestionImage))

  const changeLevel = (nextLevelId) => {
    const firstSubject = listSubjectsForLevel(teacherData.subjects, nextLevelId)[0] || null
    const firstBank = firstSubject ? listBanksForSubject(teacherData.banks, firstSubject.id)[0] || null : null
    setLevelId(nextLevelId)
    setSubjectId(firstSubject?.id || '')
    setBankId(firstBank?.id || '')
    setError('')
  }

  const changeSubject = (nextSubjectId) => {
    setSubjectId(nextSubjectId)
    setBankId(listBanksForSubject(teacherData.banks, nextSubjectId)[0]?.id || '')
    setError('')
  }

  const updateOption = (clientId, patch) => {
    setOptions((current) => current.map((option) => option.clientId === clientId ? { ...option, ...patch } : option))
  }

  const markCorrect = (clientId) => {
    setOptions((current) => current.map((option) => {
      if (questionType === 'single_choice') return { ...option, isCorrect: option.clientId === clientId }
      if (option.clientId === clientId) return { ...option, isCorrect: !option.isCorrect }
      return option
    }))
  }

  const addOption = () => setOptions((current) => [...current, makeOption()])
  const removeOption = (clientId) => {
    if (options.length <= 2) return
    setOptions((current) => current.filter((option) => option.clientId !== clientId))
  }

  const onQuestionImage = (file) => {
    const issue = validateImage(file)
    if (issue) return setError(issue)
    setError('')
    setQuestionImageFile(file)
    setRemoveQuestionImage(false)
  }

  const onOptionImage = (clientId, file) => {
    const issue = validateImage(file)
    if (issue) return setError(issue)
    setError('')
    updateOption(clientId, { imageFile: file, removeExistingImage: false })
  }

  const clearQuestionImage = () => {
    setQuestionImageFile(null)
    setRemoveQuestionImage(Boolean(questionImageAssetId))
  }

  const leaveEditor = () => {
    dispatch({
      type: 'staff',
      patch: {
        section: 'questions',
        selectedBankId: resolvedBankId || state.staff.selectedBankId,
        selectedQuestionId: null,
        editingQuestion: null,
      },
    })
  }

  const resetForAnother = () => {
    setPrompt('')
    setInstruction('')
    setQuestionImageAssetId(null)
    setQuestionImageFile(null)
    setRemoveQuestionImage(false)
    setOptions(initialOptions())
    setError('')
  }

  const openInstructionModal = () => {
    setInstructionDraft(instruction)
    setInstructionModalOpen(true)
  }

  const closeInstructionModal = () => {
    setInstructionModalOpen(false)
    window.requestAnimationFrame(() => instructionTriggerRef.current?.focus())
  }

  const saveInstruction = () => {
    setInstruction(instructionDraft.trim())
    setInstructionModalOpen(false)
    window.requestAnimationFrame(() => instructionTriggerRef.current?.focus())
  }

  const save = async ({ createAnother = false } = {}) => {
    setError('')
    if (validation) return setError(validation)
    if (!levelId || !selectedSubject || selectedSubject.academicLevelId !== levelId) {
      return setError('Choose an academic level and a subject from that level before saving.')
    }
    if (!resolvedBankId || !selectedBank || selectedBank.curriculumSubjectId !== subjectId) {
      return setError('Choose a question bank that belongs to the selected level and subject.')
    }

    setSaving(true)
    try {
      let nextQuestionImageId = questionImageAssetId
      if (questionImageFile) {
        const uploaded = await gateway.media.uploadQuestionImage(questionImageFile)
        nextQuestionImageId = uploaded.id
      } else if (removeQuestionImage) {
        nextQuestionImageId = null
      }

      const optionPayloads = []
      for (const option of options) {
        let imageAssetId = option.imageAssetId
        if (option.imageFile) {
          const uploaded = await gateway.media.uploadQuestionImage(option.imageFile)
          imageAssetId = uploaded.id
        } else if (option.removeExistingImage) {
          imageAssetId = null
        }
        optionPayloads.push({
          text: option.text.trim() || null,
          image_asset_id: imageAssetId || null,
          is_correct: option.isCorrect,
        })
      }

      const payload = {
        prompt: prompt.trim(),
        instruction: instruction.trim() || null,
        options: optionPayloads,
      }

      if (editing) {
        if (questionImageFile || removeQuestionImage) payload.image_asset_id = nextQuestionImageId
        await gateway.questions.updateQuestion(questionId, payload)
      } else {
        payload.image_asset_id = nextQuestionImageId || null
        if (questionType === 'multiple_choice') await gateway.questions.createMultipleChoiceQuestion(resolvedBankId, payload)
        else await gateway.questions.createSingleChoiceQuestion(resolvedBankId, payload)
      }

      await teacherData.refresh()
      if (!editing && createAnother) {
        resetForAnother()
        return
      }
      leaveEditor()
    } catch (requestError) {
      setError(requestError.userMessage || `Weave could not ${editing ? 'update' : 'create'} this question.`)
    } finally {
      setSaving(false)
    }
  }

  if (previewOpen) {
    return (
      <div className="question-builder-page question-preview-page">
        <header className="question-preview-page__header">
          <div><h1>Question preview</h1><p>Review exactly what the student will see before saving.</p></div>
          <button className="question-preview-back" type="button" onClick={() => setPreviewOpen(false)}><RiArrowLeftLine size={19} /> Back to editor</button>
        </header>
        <QuestionPreview
          gateway={gateway}
          questionId={questionId}
          selectedBank={selectedBank}
          questionType={questionType}
          prompt={prompt}
          instruction={instruction}
          questionImageFile={questionImageFile}
          questionImageAssetId={questionImageAssetId}
          removeQuestionImage={removeQuestionImage}
          options={options}
        />
      </div>
    )
  }

  const editor = (
    <div className="question-builder-page">
      {enableAI && !editing ? <QuestionAuthoringToolbar aiOpen={aiOpen} onToggleAI={() => setAIOpen((open) => !open)} onBack={leaveEditor} onPreview={() => setPreviewOpen(true)} onSave={(createAnother) => save({ createAnother })} busy={saving || loading} /> : (
      <header className="question-builder-toolbar" aria-label="Question editor actions">
        <button className="question-builder-back" type="button" onClick={leaveEditor}><RiArrowLeftLine size={17} /> Questions</button>
        <div className="question-builder-header__actions">
          <button className="teacher-secondary-action" type="button" disabled={saving} onClick={leaveEditor}>Cancel</button>
          {!editing && (
            <button className="teacher-secondary-action question-builder-create-another" type="button" disabled={saving || loading} onClick={() => save({ createAnother: true })}>
              <RiAddLine size={18} /> Save & create another
            </button>
          )}
          <button className="teacher-primary-action" type="button" disabled={saving || loading} onClick={() => save({ createAnother: false })}>
            <RiSave3Line size={18} /> {saving ? 'Saving…' : 'Save & close'}
          </button>
        </div>
      </header>
      )}

      {error && <Notice tone="danger">{error}</Notice>}
      {loading ? <div className="question-builder-loading">Loading question…</div> : (
        <div className="question-builder-grid">
          <section className="question-builder-card question-builder-content-card">
            <div className="question-builder-card__heading"><div><span>01</span><h2>Question content</h2></div><p>Choose the academic scope first, then enter the question and any helpful details.</p></div>
            <div className="question-builder-meta-fields">
              <div className="question-builder-field">
                <span>Academic level</span>
                <SelectControl label="Academic level" value={levelId} options={levelOptions} onChange={changeLevel} disabled={editing} placeholder="Choose level" />
              </div>
              <div className="question-builder-field">
                <span>Subject</span>
                <SelectControl label="Subject" value={subjectId} options={subjectOptions} onChange={changeSubject} disabled={editing || !levelId || !subjectOptions.length} placeholder={levelId ? 'Choose subject' : 'Choose a level first'} />
              </div>
              <div className="question-builder-field">
                <span>Question bank</span>
                <SelectControl label="Question bank" value={resolvedBankId} options={bankOptions} onChange={(value) => { setBankId(value); setError('') }} disabled={editing || !subjectId || !bankOptions.length} placeholder={subjectId ? 'Choose a bank' : 'Choose a subject first'} />
                {!editing && subjectId && <small>Only banks for this level and subject are shown.</small>}
              </div>
              <div className="question-builder-field question-instruction-field">
                <span>Instruction <small>(optional)</small></span>
                <button ref={instructionTriggerRef} className={`question-instruction-trigger${instruction ? ' has-value' : ''}`} type="button" onClick={openInstructionModal}>
                  <span className="question-instruction-trigger__icon"><RiAddLine size={20} /></span>
                  <strong>Add instruction</strong>
                </button>
              </div>
            </div>
            <div className="question-builder-field question-builder-field--wide">
              <span>Question prompt</span>
              <RichTextToolbar textareaRef={promptRef} value={prompt} onChange={setPrompt} onImage={onQuestionImage} hasImage={hasQuestionImage} onRemoveImage={clearQuestionImage} />
              <textarea ref={promptRef} aria-label="Question prompt" rows="6" value={prompt} onChange={(event) => setPrompt(event.target.value)} placeholder="Type your question here…" />
              {hasQuestionImage && (
                <div className="question-prompt-image-preview">
                  <div className="question-prompt-image-thumbnail">
                    {questionImageFile ? <LocalImage file={questionImageFile} alt="Question image preview" /> : <QuestionMedia gateway={gateway} questionId={questionId} alt="Question image preview" />}
                  </div>
                  <button type="button" className="text-button" onClick={clearQuestionImage}><RiDeleteBin6Line size={16} /> Remove image</button>
                </div>
              )}
            </div>
          </section>

          <div className="question-builder-side">
            <section className="question-builder-card question-builder-card--options">
              <div className="question-builder-options-header">
                <div><span>02</span><div><h2>Answer options</h2><p>{questionType === 'single_choice' ? 'Add choices and mark one correct answer.' : 'Add choices and mark two or more correct answers.'}</p></div></div>
                <div className="question-type-switch" role="group" aria-label="Answer type">
                  <button type="button" disabled={editing} className={questionType === 'single_choice' ? 'active' : ''} onClick={() => setQuestionType('single_choice')}>Single choice</button>
                  <button type="button" disabled={editing} className={questionType === 'multiple_choice' ? 'active' : ''} onClick={() => setQuestionType('multiple_choice')}>Multiple choice</button>
                </div>
              </div>
              {editing && <p className="question-type-note">Question type and academic scope are fixed after creation.</p>}
              <div className="question-option-stack">
                {options.map((option, index) => {
                  const hasImage = option.imageFile || (option.imageAssetId && !option.removeExistingImage)
                  return (
                    <article className={`question-option-editor ${option.isCorrect ? 'is-correct' : ''}`} key={option.clientId}>
                      <div className="question-option-editor__row">
                        <button className="question-option-correct" type="button" onClick={() => markCorrect(option.clientId)} aria-label={`Mark option ${optionLetter(index)} correct`} aria-pressed={option.isCorrect}><span>{option.isCorrect ? '✓' : ''}</span></button>
                        <strong className="question-option-letter">{optionLetter(index)}</strong>
                        <input className="question-option-text-input" value={option.text} onChange={(event) => updateOption(option.clientId, { text: event.target.value })} placeholder={`Enter option ${optionLetter(index)}…`} />
                        <label className={`question-option-image-button ${hasImage ? 'active' : ''}`} title={hasImage ? 'Replace image' : 'Upload image'} aria-label={hasImage ? `Replace image for option ${optionLetter(index)}` : `Upload image for option ${optionLetter(index)}`}><RiImageAddLine size={21} /><input type="file" accept="image/jpeg,image/png,image/webp" onChange={(event) => event.target.files?.[0] && onOptionImage(option.clientId, event.target.files[0])} /></label>
                        <button type="button" className="question-option-delete" disabled={options.length <= 2} onClick={() => removeOption(option.clientId)} aria-label={`Remove option ${optionLetter(index)}`}><RiDeleteBin6Line size={18} /></button>
                      </div>
                      {hasImage && (
                        <div className="question-option-image-preview">
                          <div className="question-option-thumbnail">{option.imageFile ? <LocalImage file={option.imageFile} alt={`Option ${optionLetter(index)}`} /> : <QuestionMedia gateway={gateway} questionId={questionId} optionId={option.id} alt={`Option ${optionLetter(index)}`} />}</div>
                          <button type="button" className="text-button" onClick={() => updateOption(option.clientId, { imageFile: null, removeExistingImage: Boolean(option.imageAssetId) })}>Remove image</button>
                        </div>
                      )}
                    </article>
                  )
                })}
              </div>
              <button className="question-builder-add-option" type="button" onClick={addOption}><RiAddLine size={19} /> Add option</button>
              <div className="question-builder-rule"><strong>{correctCount}</strong><span>option{correctCount === 1 ? '' : 's'} marked correct</span></div>
            </section>
            {!enableAI && <button className="question-preview-toggle" type="button" onClick={() => setPreviewOpen(true)}><RiEyeLine size={21} /> Preview question</button>}
          </div>
        </div>
      )}
      {instructionModalOpen && typeof document !== 'undefined' && createPortal(
        <div className="question-instruction-backdrop" onMouseDown={(event) => { if (event.currentTarget === event.target) closeInstructionModal() }}>
          <section className="question-instruction-modal" role="dialog" aria-modal="true" aria-labelledby="question-instruction-title" aria-describedby="question-instruction-description">
            <header className="question-instruction-modal__header">
              <div>
                <span className="question-instruction-modal__icon"><RiAddLine size={22} /></span>
                <div>
                  <h2 id="question-instruction-title">{instruction ? 'Edit instruction' : 'Add instruction'}</h2>
                  <p id="question-instruction-description">Add guidance the student should read before answering.</p>
                </div>
              </div>
            </header>
            <div className="question-builder-field question-instruction-modal__editor">
              <span>Instruction text</span>
              <RichTextToolbar textareaRef={instructionRef} value={instructionDraft} onChange={setInstructionDraft} />
              <textarea ref={instructionRef} aria-label="Instruction text" rows="7" value={instructionDraft} onChange={(event) => setInstructionDraft(event.target.value)} placeholder="e.g. Choose the best answer." />
              <small>{instruction ? 'Clear the text and save to remove this instruction.' : 'This is optional and can be added later.'}</small>
            </div>
            <footer className="question-instruction-modal__actions">
              <button className="question-instruction-modal__cancel" type="button" onClick={closeInstructionModal}>Cancel</button>
              <button className="question-instruction-modal__save" type="button" onClick={saveInstruction}>Save instruction</button>
            </footer>
          </section>
        </div>,
        document.querySelector('.weave-app') || document.body,
      )}
    </div>
  )
  if (!enableAI || editing) return editor
  return <QuestionAuthoringWorkspace open={aiOpen} panel={state.staff.section !== 'review-ai-questions' ? <TeacherAIComposer bank={selectedBank} state={state} dispatch={dispatch} gateway={gateway} onClose={() => setAIOpen(false)} /> : null}>{editor}</QuestionAuthoringWorkspace>
}

function validateDraft({ prompt, questionType, options }) {
  if (!prompt.trim()) return 'Write the question prompt before saving.'
  if (options.length < 2) return 'A question must have at least two answer options.'
  if (options.some((option) => !option.text.trim() && !option.imageFile && !(option.imageAssetId && !option.removeExistingImage))) return 'Every answer option needs text, an image, or both.'
  const correctCount = options.filter((option) => option.isCorrect).length
  if (questionType === 'single_choice' && correctCount !== 1) return 'Single-choice questions require exactly one correct answer.'
  if (questionType === 'multiple_choice' && correctCount < 2) return 'Multiple-choice questions require at least two correct answers.'
  if (questionType === 'multiple_choice' && correctCount === options.length) return 'Multiple-choice questions need at least one incorrect answer.'
  const textOptions = options.map((option) => option.text.trim().toLowerCase()).filter(Boolean)
  if (new Set(textOptions).size !== textOptions.length) return 'Answer text must be unique within the question.'
  return ''
}

function validateImage(file) {
  if (!file) return ''
  if (!IMAGE_TYPES.has(file.type)) return 'Use a JPEG, PNG, or WebP image.'
  if (file.size > MAX_IMAGE_SIZE) return 'Images must be 5 MB or smaller.'
  return ''
}

function RichTextToolbar({ textareaRef, value, onChange, onImage, hasImage = false, onRemoveImage }) {
  const apply = (kind) => applyTextFormat({ textarea: textareaRef.current, value, onChange, kind })
  return (
    <div className="question-format-toolbar" role="toolbar" aria-label="Text formatting">
      <button type="button" title="Bold" aria-label="Bold" onClick={() => apply('bold')}><RiBold size={18} /></button>
      <button type="button" title="Italic" aria-label="Italic" onClick={() => apply('italic')}><RiItalic size={18} /></button>
      <button type="button" title="Underline" aria-label="Underline" onClick={() => apply('underline')}><RiUnderline size={18} /></button>
      <span aria-hidden="true" />
      <button type="button" title="Bulleted list" aria-label="Bulleted list" onClick={() => apply('bullet')}><RiListUnordered size={18} /></button>
      <button type="button" title="Numbered list" aria-label="Numbered list" onClick={() => apply('number')}><RiListOrdered size={18} /></button>
      <button type="button" title="Link" aria-label="Link" onClick={() => apply('link')}><RiLink size={18} /></button>
      {onImage && <label className={hasImage ? 'active' : ''} title={hasImage ? 'Replace question image' : 'Add question image'} aria-label={hasImage ? 'Replace question image' : 'Add question image'}><RiImageLine size={18} /><input type="file" accept="image/jpeg,image/png,image/webp" onChange={(event) => event.target.files?.[0] && onImage(event.target.files[0])} /></label>}
      {hasImage && <button className="question-format-toolbar__remove-image" type="button" title="Remove question image" aria-label="Remove question image" onClick={onRemoveImage}><RiDeleteBin6Line size={17} /></button>}
      <button type="button" title="Superscript" aria-label="Superscript" onClick={() => apply('superscript')}><RiSuperscript2 size={18} /></button>
    </div>
  )
}

export function QuestionPreview({ gateway, questionId, selectedBank, questionType, prompt, instruction, questionImageSrc, questionImageFile, questionImageAssetId, removeQuestionImage, options, previewLabel = 'Unsaved preview', previewTone = 'info' }) {
  return (
    <aside className="question-preview-card question-preview-card--page" aria-label="Student question preview">
      <div className="question-preview-card__heading"><div><span>Student view</span><StatusBadge tone={previewTone}>{previewLabel}</StatusBadge></div><small>{selectedBank?.name || 'Question bank'}</small></div>
      <div className="premium-exam-content question-builder-student-preview">
        {instruction.trim() && <p className="question-preview-instruction"><FormattedText text={instruction} /></p>}
        <div className="premium-question-prompt"><FormattedText text={prompt} placeholder="Your question will appear here as you type." /></div>
        {(questionImageSrc || questionImageFile || (questionImageAssetId && !removeQuestionImage)) && (
          <div className="premium-question-media">{questionImageSrc ? <img src={questionImageSrc} alt="Question illustration" /> : questionImageFile ? <LocalImage file={questionImageFile} alt="Question preview" /> : <QuestionMedia gateway={gateway} questionId={questionId} alt="Question preview" />}</div>
        )}
        <div className="premium-options-list">
          {options.map((option, index) => (
            <div className="premium-option" key={option.clientId}>
              <div className="premium-option-letter">{optionLetter(index)}</div>
              <div className="premium-option-content">
                {option.text.trim() && <div className="premium-option-text"><FormattedText text={option.text} /></div>}
                {(option.imageSrc || option.imageFile || (option.imageAssetId && !option.removeExistingImage)) && (
                  <div className="premium-option-media">{option.imageSrc ? <img src={option.imageSrc} alt={`Option ${optionLetter(index)}`} /> : option.imageFile ? <LocalImage file={option.imageFile} alt={`Option ${optionLetter(index)}`} /> : <QuestionMedia gateway={gateway} questionId={questionId} optionId={option.id} alt={`Option ${optionLetter(index)}`} />}</div>
                )}
                {!option.text.trim() && !option.imageSrc && !option.imageFile && !(option.imageAssetId && !option.removeExistingImage) && <div className="premium-option-text question-preview-placeholder">Add answer text or an image</div>}
              </div>
            </div>
          ))}
        </div>
      </div>
      <footer><span>{questionType === 'single_choice' ? 'Single choice' : 'Multiple choice'}</span><span>{options.length} options</span></footer>
    </aside>
  )
}

function applyTextFormat({ textarea, value, onChange, kind }) {
  if (!textarea) return
  const start = textarea.selectionStart
  const end = textarea.selectionEnd
  const selection = value.slice(start, end)
  const inline = {
    bold: ['**', '**', 'bold text'],
    italic: ['*', '*', 'italic text'],
    underline: ['__', '__', 'underlined text'],
    superscript: ['^', '^', 'superscript'],
  }
  let replacement = selection
  if (inline[kind]) {
    const [before, after, fallback] = inline[kind]
    replacement = `${before}${selection || fallback}${after}`
  } else if (kind === 'link') {
    replacement = `[${selection || 'link text'}](https://)`
  } else {
    const lines = (selection || 'List item').split('\n')
    replacement = lines.map((line, index) => `${kind === 'number' ? `${index + 1}.` : '-'} ${line}`).join('\n')
  }
  onChange(`${value.slice(0, start)}${replacement}${value.slice(end)}`)
  requestAnimationFrame(() => {
    textarea.focus()
    textarea.setSelectionRange(start, start + replacement.length)
  })
}

function LocalImage({ file, alt }) {
  const [url, setUrl] = useState('')
  useEffect(() => {
    if (!file || typeof URL.createObjectURL !== 'function') return undefined
    const objectUrl = URL.createObjectURL(file)
    const frame = window.requestAnimationFrame(() => setUrl(objectUrl))
    return () => {
      window.cancelAnimationFrame(frame)
      URL.revokeObjectURL(objectUrl)
    }
  }, [file])
  return url ? <img src={url} alt={alt} /> : <span className="question-media-loading">Preparing preview…</span>
}

function QuestionMedia({ gateway, questionId, optionId, alt }) {
  const [url, setUrl] = useState('')
  useEffect(() => {
    if (!questionId || optionId === null) return undefined
    let cancelled = false
    let objectUrl = ''
    const request = optionId
      ? gateway.questions.getQuestionOptionImage(questionId, optionId)
      : gateway.questions.getQuestionImage(questionId)
    request.then((blob) => {
      if (cancelled) return
      objectUrl = URL.createObjectURL(blob)
      setUrl(objectUrl)
    }).catch(() => null)
    return () => {
      cancelled = true
      if (objectUrl) URL.revokeObjectURL(objectUrl)
    }
  }, [gateway, optionId, questionId])
  return url ? <img src={url} alt={alt} /> : <span className="question-media-loading">Loading image…</span>
}

function optionLetter(index) {
  return String.fromCharCode(65 + (index % 26))
}