import { useImagePreview } from '../../shared/useImagePreview'
import { useEffect, useMemo, useRef, useState } from 'react'
import { RiCloseLine, RiImageAddLine } from '@remixicon/react'
import { Icon } from '../../shared/icons/Icon'
import { Notice, PageTitle, Panel } from '../../shared/ui'

const MAX_QUESTION_IMAGE_SIZE = 5 * 1024 * 1024
const QUESTION_IMAGE_TYPES = new Set(['image/jpeg', 'image/png', 'image/webp'])

function normalizeQuestion(question, banks) {
  const bank = banks.find((item) => item.id === question.bank_id || item.id === question.bankId)
  const questionType = question.question_type || question.type
  return {
    id: question.id,
    bankId: question.bank_id || question.bankId,
    bankName: bank?.name || question.bankName || 'Question bank',
    prompt: question.prompt || '',
    instruction: question.instruction || '',
    type: questionType === 'multiple_choice' || questionType === 'Multiple choice' ? 'Multiple choice' : 'Single choice',
    image: Boolean(question.image_asset_id || question.imageAssetId || question.image),
    imageAssetId: question.image_asset_id || question.imageAssetId || null,
    version: question.version || 1,
    options: question.options || [],
  }
}

export function EditQuestionPage(props) {
  return <EditQuestionContent key={props.state.staff.selectedQuestionId || 'none'} {...props} />
}

function EditQuestionContent({ state, dispatch, teacherData, gateway }) {
  const questionId = state.staff.selectedQuestionId
  const cachedQuestion = useMemo(() => {
    const stored = state.staff.editingQuestion
    if (stored?.id === questionId) return normalizeQuestion(stored, teacherData.banks)
    const listed = teacherData.questions?.find((question) => question.id === questionId)
    return listed ? normalizeQuestion(listed, teacherData.banks) : null
  }, [questionId, state.staff.editingQuestion, teacherData.banks, teacherData.questions])

  const [question, setQuestion] = useState(cachedQuestion)
  const [loading, setLoading] = useState(Boolean(questionId && !cachedQuestion))
  const [loadError, setLoadError] = useState(questionId ? '' : 'No question was selected for editing.')
  const [prompt, setPrompt] = useState(cachedQuestion?.prompt || '')
  const [instruction, setInstruction] = useState(cachedQuestion?.instruction || '')
  const [options, setOptions] = useState(() => toEditableOptions(cachedQuestion?.options || []))
  const [imageFile, imagePreviewUrl, setImageFile] = useImagePreview()
  const [removeExistingImage, setRemoveExistingImage] = useState(false)
  const [error, setError] = useState('')
  const [saving, setSaving] = useState(false)
  const [saveStage, setSaveStage] = useState('')
  const imageInputRef = useRef(null)

  useEffect(() => {
    if (!questionId) return undefined

    let cancelled = false

    gateway.questions.getQuestion(questionId)
      .then((rawQuestion) => {
        if (cancelled) return
        const next = normalizeQuestion(rawQuestion, teacherData.banks)
        setQuestion(next)
        setPrompt(next.prompt)
        setInstruction(next.instruction || '')
        setOptions(toEditableOptions(next.options))
        setRemoveExistingImage(false)
      })
      .catch((requestError) => {
        if (cancelled) return
        if (!cachedQuestion) {
          setLoadError(requestError.userMessage || requestError.message || 'Weave could not load this question for editing.')
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })

    return () => {
      cancelled = true
    }
  }, [cachedQuestion, gateway.questions, questionId, teacherData.banks])


  const leaveEditor = () => {
    dispatch({
      type: 'staff',
      patch: { section: 'questions', selectedQuestionId: null, editingQuestion: null },
    })
  }

  const selectImage = (event) => {
    const file = event.target.files?.[0]
    setError('')
    if (!file) return
    if (!QUESTION_IMAGE_TYPES.has(file.type)) {
      setImageFile(null)
      event.target.value = ''
      setError('Choose a PNG, JPEG, or WebP image.')
      return
    }
    if (file.size > MAX_QUESTION_IMAGE_SIZE) {
      setImageFile(null)
      event.target.value = ''
      setError('Question images must be 5 MB or smaller.')
      return
    }
    setImageFile(file)
    setRemoveExistingImage(false)
  }

  const removeSelectedImage = () => {
    setImageFile(null)
    if (imageInputRef.current) imageInputRef.current.value = ''
  }

  const toggleCorrect = (index) => {
    setOptions((current) => current.map((option, optionIndex) => {
      if (question.type === 'Single choice') {
        return { ...option, isCorrect: optionIndex === index }
      }
      if (optionIndex !== index) return option
      return { ...option, isCorrect: !option.isCorrect }
    }))
  }

  const updateOptionText = (index, value) => {
    setOptions((current) => current.map((option, optionIndex) => optionIndex === index ? { ...option, text: value } : option))
  }

  const removeOption = (index) => {
    setOptions((current) => current.filter((_, optionIndex) => optionIndex !== index))
  }

  const addOption = () => {
    setOptions((current) => [...current, { text: '', isCorrect: false }])
  }

  const saveQuestion = async () => {
    setError('')
    if (!question) return
    if (!prompt.trim()) {
      setError('Question prompt is required.')
      return
    }

    const normalizedOptions = options
      .map((option) => ({ text: option.text.trim(), is_correct: option.isCorrect }))
      .filter((option) => option.text)

    if (normalizedOptions.length < 2) {
      setError('At least two answer options are required.')
      return
    }

    setSaving(true)
    try {
      const payload = {
        prompt: prompt.trim(),
        instruction: instruction.trim() || null,
        options: normalizedOptions,
      }

      if (imageFile) {
        setSaveStage('Uploading image…')
        const asset = await gateway.media.uploadQuestionImage(imageFile)
        payload.image_asset_id = asset.id
      } else if (question.image && removeExistingImage) {
        payload.image_asset_id = null
      }

      setSaveStage('Saving changes…')
      await gateway.questions.updateQuestion(question.id, payload)
      await teacherData.refresh()
      leaveEditor()
    } catch (saveError) {
      setError(saveError.userMessage || saveError.message || 'Weave could not update this question.')
    } finally {
      setSaving(false)
      setSaveStage('')
    }
  }

  if (loading && !question) {
    return <div className="teacher-page-loading">Loading question editor…</div>
  }

  if (!question) {
    return (
      <div className="teacher-reference-page">
        <PageTitle title="Edit Question" subtitle="The question editor could not be opened." />
        <Notice tone="danger">{loadError || 'The selected question is no longer available in your current teaching scope.'}</Notice>
        <div><button className="button button--secondary" type="button" onClick={leaveEditor}>Back to Questions</button></div>
      </div>
    )
  }

  const selectedBank = teacherData.banks.find((bank) => bank.id === question.bankId)

  return (
    <div className="teacher-reference-page teacher-question-editor">
      <div className="teacher-page-head">
        <div>
          <button className="text-button" type="button" onClick={leaveEditor}>Back to questions</button>
          <PageTitle
            title="Edit Question"
            subtitle={`Editing ${selectedBank?.name || question.bankName}. Saving a change creates version ${question.version + 1}.`}
          />
        </div>
        <div className="toolbar">
          <button className="button button--primary" type="button" disabled={saving} onClick={saveQuestion}>
            {saving ? saveStage || 'Saving…' : 'Save Changes'}
          </button>
        </div>
      </div>

      {loadError && <Notice tone="warning">The latest question copy could not be refreshed. You can still edit the loaded copy.</Notice>}
      {error && <Notice tone="danger">{error}</Notice>}

      <div className="authoring-grid">
        <Panel title="Question content">
          <label className="field-stack">
            <span>Question Bank</span>
            <select aria-label="Question Bank" value={question.bankId} disabled>
              <option value={question.bankId}>{selectedBank?.name || question.bankName}</option>
            </select>
          </label>

          <label className="field-stack">
            <span>Prompt</span>
            <textarea aria-label="Question prompt" value={prompt} onChange={(event) => setPrompt(event.target.value)} />
          </label>

          <label className="field-stack">
            <span>Instruction</span>
            <textarea aria-label="Question instruction" value={instruction} onChange={(event) => setInstruction(event.target.value)} />
          </label>

          <div className="field-stack">
            <span>Question image <small>(optional)</small></span>
            <div className="upload-zone question-image-upload">
              {imagePreviewUrl ? <img src={imagePreviewUrl} alt="Selected question" /> : <span className="question-image-placeholder"><RiImageAddLine size={30} aria-hidden="true" /></span>}
              <div className="question-image-upload__copy">
                <strong>{imageFile ? imageFile.name : question.image && !removeExistingImage ? 'Current question image' : 'Add a diagram or reference image'}</strong>
                <p>{imageFile ? formatFileSize(imageFile.size) : question.image && !removeExistingImage ? 'Choose a new image to replace it, or remove it.' : 'PNG, JPEG, or WebP. Maximum 5 MB.'}</p>
                <div className="toolbar">
                  <label className="button button--secondary" htmlFor="edit-question-image-upload">{imageFile ? 'Replace image' : 'Choose image'}</label>
                  {imageFile && <button className="button button--ghost" type="button" onClick={removeSelectedImage}><RiCloseLine size={16} /> Remove</button>}
                  {!imageFile && question.image && !removeExistingImage && <button className="button button--ghost" type="button" onClick={() => setRemoveExistingImage(true)}><RiCloseLine size={16} /> Remove current image</button>}
                </div>
                <input ref={imageInputRef} id="edit-question-image-upload" className="question-image-input" type="file" accept="image/png,image/jpeg,image/webp" onChange={selectImage} />
              </div>
            </div>
          </div>
        </Panel>

        <Panel title="Question settings">
          <div className="teacher-question-type-lock">
            <span>Question Type</span>
            <strong>{question.type}</strong>
            <small>The backend keeps the question type fixed after creation.</small>
          </div>

          <div className="answer-options">
            {options.map((option, index) => {
              const optionLabel = String.fromCharCode(65 + index)
              return (
                <label key={`${optionLabel}-${index}`} className="answer-option-row">
                  <input
                    type={question.type === 'Single choice' ? 'radio' : 'checkbox'}
                    name={question.type === 'Single choice' ? `question-${question.id}-correct` : undefined}
                    checked={option.isCorrect}
                    onChange={() => toggleCorrect(index)}
                  />
                  <span>{optionLabel}</span>
                  <input aria-label={`Option ${optionLabel}`} value={option.text} onChange={(event) => updateOptionText(index, event.target.value)} />
                  <button type="button" aria-label={`Delete option ${optionLabel}`} onClick={() => removeOption(index)}><Icon name="trash" size={16} /></button>
                </label>
              )
            })}
            <button className="button button--secondary" type="button" onClick={addOption}><Icon name="plus" size={16} /> Add Option</button>
          </div>

          <Notice tone="success">{question.type === 'Single choice' ? 'Exactly one answer must be correct.' : 'Multiple-choice questions must keep at least two correct answers and at least one incorrect answer.'}</Notice>
        </Panel>
      </div>
    </div>
  )
}

function toEditableOptions(options) {
  return options.map((option) => ({
    text: option.text || '',
    isCorrect: Boolean(option.is_correct ?? option.isCorrect),
  }))
}

function formatFileSize(size) {
  if (size < 1024) return `${size} bytes`
  if (size < 1024 * 1024) return `${Math.round(size / 1024)} KB`
  return `${(size / (1024 * 1024)).toFixed(1)} MB`
}
