import { useEffect, useMemo, useRef, useState } from 'react'
import { RiArrowLeftLine } from '@remixicon/react'
import { Notice, StatusBadge } from '../../shared/ui'
import { FormattedText } from '../../shared/ui/FormattedText'
import './question-builder.css'

export function TeacherQuestionPreviewPage(props) {
  return <TeacherQuestionPreviewContent key={props.state.staff.selectedQuestionId || 'none'} {...props} />
}

function TeacherQuestionPreviewContent({ state, dispatch, teacherData, gateway }) {
  const questionId = state.staff.selectedQuestionId
  const headingRef = useRef(null)
  useEffect(() => {
    headingRef.current?.focus()
    headingRef.current?.scrollIntoView?.({ block: 'start' })
  }, [questionId])
  const [question, setQuestion] = useState(null)
  const [loading, setLoading] = useState(Boolean(questionId))
  const [error, setError] = useState(questionId ? '' : 'Choose a question to preview it.')

  useEffect(() => {
    if (!questionId) return undefined
    let cancelled = false
    gateway.questions.getQuestion(questionId)
      .then((loadedQuestion) => {
        if (!cancelled) setQuestion(loadedQuestion)
      })
      .catch((requestError) => {
        if (!cancelled) setError(requestError.userMessage || 'Weave could not load this question preview.')
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => { cancelled = true }
  }, [gateway, questionId])

  const options = useMemo(() => (question?.options || []).map((option, index) => ({
    clientId: option.id || `preview-option-${index}`,
    id: option.id || null,
    text: option.text || '',
    isCorrect: Boolean(option.is_correct),
    imageAssetId: option.image_asset_id || null,
  })), [question])

  const selectedBank = teacherData.banks.find((bank) => bank.id === question?.bank_id)
  const returnToBank = state.staff.questionPreviewOrigin === 'bank-detail'
  const returnToExam = state.staff.questionPreviewOrigin === 'create-exam'
  const returnSection = returnToExam ? 'create-exam' : returnToBank ? 'bank-detail' : 'questions'
  const returnLabel = returnToExam ? 'Back to exam form' : returnToBank ? `Back to ${selectedBank?.name || 'question bank'}` : 'Back to questions'
  const leavePreview = () => dispatch({
    type: 'staff',
    patch: {
      section: returnSection,
      selectedBankId: question?.bank_id || state.staff.selectedBankId,
      selectedQuestionId: null,
      editingQuestion: null,
      questionPreviewOrigin: null,
    },
  })

  return (
    <div className="question-builder-page question-preview-page">
      <header className="question-preview-page__header">
        <div><h1 ref={headingRef} tabIndex={-1}>Question preview</h1><p>Review exactly how this saved question appears to students.</p></div>
        <button className="question-preview-back" type="button" onClick={leavePreview}><RiArrowLeftLine size={19} /> {returnLabel}</button>
      </header>
      {error && <Notice tone="danger">{error}</Notice>}
      {loading && <div className="question-builder-loading">Loading question preview…</div>}
      {!loading && question && (
        <SavedQuestionPreview
          gateway={gateway}
          question={question}
          selectedBank={selectedBank}
          options={options}
        />
      )}
    </div>
  )
}

function SavedQuestionPreview({ gateway, question, selectedBank, options }) {
  const questionType = question.question_type
  const prompt = question.prompt || ''
  const instruction = question.instruction || ''

  return (
    <aside className="question-preview-card question-preview-card--page" aria-label="Student question preview">
      <div className="question-preview-card__heading"><div><span>Student view</span><StatusBadge tone="success">Saved question</StatusBadge></div><small>{selectedBank?.name || 'Question bank'}</small></div>
      <div className="premium-exam-content question-builder-student-preview">
        <div className="premium-question-header"><h2>Authored by: {question.author_name}</h2></div>
        {instruction.trim() && <p className="question-preview-instruction"><FormattedText text={instruction} /></p>}
        <div className="premium-question-prompt"><FormattedText text={prompt} /></div>
        {question.image_asset_id && (
          <div className="premium-question-media"><QuestionMedia gateway={gateway} questionId={question.id} alt="Question preview" /></div>
        )}
        <div className="premium-options-list">
          {options.map((option, index) => (
            <div className="premium-option" key={option.clientId}>
              <div className="premium-option-letter">{optionLetter(index)}</div>
              <div className="premium-option-content">
                {option.text.trim() && <div className="premium-option-text">{option.text}</div>}
                {option.imageAssetId && (
                  <div className="premium-option-media"><QuestionMedia gateway={gateway} questionId={question.id} optionId={option.id} alt={`Option ${optionLetter(index)}`} /></div>
                )}
              </div>
            </div>
          ))}
        </div>
      </div>
      <footer><span>{questionType === 'single_choice' ? 'Single choice' : 'Multiple choice'}</span><span>{options.length} options</span></footer>
    </aside>
  )
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
