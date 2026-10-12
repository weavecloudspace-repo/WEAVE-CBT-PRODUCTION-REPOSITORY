import { useEffect, useMemo, useRef, useState } from 'react'
import { RiArrowLeftLine, RiArrowRightLine, RiInformationLine, RiRefreshLine, RiSearchLine } from '@remixicon/react'
import { Icon } from '../../shared/icons/Icon'
import { Notice, PageTitle, StatusBadge } from '../../shared/ui'
import { QuestionRows } from './components'
import { statusTone } from './utils'

export function QuestionBanksPage({ dispatch, teacherData }) {
  const [query, setQuery] = useState('')
  const [helpOpen, setHelpOpen] = useState(false)
  const helpRef = useRef(null)
  const banks = useMemo(() => {
    const needle = query.trim().toLowerCase()
    if (!needle) return teacherData.banks
    return teacherData.banks.filter((bank) => `${bank.name} ${bank.description || ''} ${bank.academicLevelName || ''} ${bank.subjectName || ''} ${bank.subjectCode || ''}`.toLowerCase().includes(needle))
  }, [query, teacherData.banks])

  useEffect(() => {
    if (!helpOpen) return undefined

    const closeOnOutsideClick = (event) => {
      if (!helpRef.current?.contains(event.target)) setHelpOpen(false)
    }
    const closeOnEscape = (event) => {
      if (event.key === 'Escape') setHelpOpen(false)
    }

    document.addEventListener('pointerdown', closeOnOutsideClick)
    document.addEventListener('keydown', closeOnEscape)
    return () => {
      document.removeEventListener('pointerdown', closeOnOutsideClick)
      document.removeEventListener('keydown', closeOnEscape)
    }
  }, [helpOpen])

  return (
    <div className="teacher-reference-page">
      <div className="teacher-page-heading teacher-page-heading--with-search">
        <div>
          <div className="teacher-page-title-line">
            <span className="teacher-page-title-icon"><Icon name="bank" size={27} /></span>
            <h1>Question Banks</h1>
          </div>
          <p>These are the question banks you are currently authorized to contribute to.</p>
        </div>
        <label className="teacher-search-control">
          <RiSearchLine size={17} aria-hidden="true" />
          <input aria-label="Search question banks" type="search" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search banks, levels or subjects..." />
        </label>
      </div>

      {teacherData.error && <Notice tone="danger">{teacherData.error}</Notice>}

      {teacherData.loading && <div className="teacher-page-loading">Loading your question banks…</div>}
      {!teacherData.loading && teacherData.banks.length === 0 && (
        <div className="teacher-reference-empty teacher-reference-empty--large">
          <Icon name="bank" size={30} />
          <div><strong>No authorable question banks</strong><p>Your administrator creates question banks. Banks assigned to your teaching scope will appear here automatically.</p></div>
        </div>
      )}

      <section className="teacher-bank-grid" aria-label="Authorable question banks">
        {banks.map((bank) => (
          <article key={bank.id} className="teacher-bank-card">
            <span className="teacher-bank-card__icon"><Icon name="bank" size={22} /></span>
            <div className="teacher-bank-card__body">
              {(bank.academicLevelName || bank.subjectName) && (
                <div className="admin-bank-card__subject">
                  {bank.academicLevelName ? `${bank.academicLevelName} · ` : ''}{bank.subjectName || 'Subject'}{bank.subjectCode ? ` · ${bank.subjectCode}` : ''}
                </div>
              )}
              <h2>{bank.name}</h2>
              <p>{bank.description || 'Question bank available for your current teaching assignment.'}</p>
              <div className="teacher-bank-card__meta">
                <span>{bank.count} {bank.count === 1 ? 'question' : 'questions'}</span>
                <StatusBadge tone={statusTone(bank.status)}>{bank.status}</StatusBadge>
              </div>
            </div>
            <button
              type="button"
              className="teacher-bank-card__action"
              onClick={() => dispatch({ type: 'staff', patch: { section: 'bank-detail', selectedBankId: bank.id } })}
            >
              View Questions <RiArrowRightLine size={16} aria-hidden="true" />
            </button>
          </article>
        ))}
      </section>

      {!teacherData.loading && teacherData.banks.length > 0 && banks.length === 0 && (
        <div className="teacher-reference-empty teacher-reference-empty--compact"><div><strong>No matching banks</strong><p>Try another bank, level, or subject name or clear the search.</p></div></div>
      )}

      <aside ref={helpRef} className="teacher-bank-help">
        <button
          type="button"
          className="teacher-bank-help__trigger"
          aria-label="Question bank help"
          aria-expanded={helpOpen}
          aria-controls="question-bank-help-card"
          onClick={() => setHelpOpen((open) => !open)}
        >
          <RiInformationLine size={22} aria-hidden="true" />
        </button>
        {helpOpen && (
          <div id="question-bank-help-card" className="teacher-bank-help__card" role="dialog" aria-label="Question bank help">
            <div className="teacher-bank-help__title">
              <span><RiInformationLine size={20} aria-hidden="true" /></span>
              <strong>Can’t find a bank?</strong>
            </div>
            <p>You only see banks that match your current Weave teaching authorization. If something is missing, ask your school administrator to check your assignment.</p>
            <button
              type="button"
              className="teacher-bank-help__refresh"
              onClick={() => {
                setHelpOpen(false)
                teacherData.refresh()
              }}
            >
              <RiRefreshLine size={17} aria-hidden="true" /> Refresh banks
            </button>
          </div>
        )}
      </aside>
    </div>
  )
}

export function BankDetailPage({ state, dispatch, teacherData }) {
  const bank = teacherData.banks.find((item) => item.id === state.staff.selectedBankId) || teacherData.banks[0]
  const questions = bank ? teacherData.questions.filter((question) => question.bankId === bank.id) : []

  if (!bank) {
    return <><PageTitle title="Question Bank" subtitle="No bank selected." /><Notice>No authorable question banks were returned by the backend.</Notice></>
  }

  const previewQuestion = (question) => {
    dispatch({
      type: 'staff',
      patch: {
        section: 'preview-question',
        selectedBankId: question.bankId,
        selectedQuestionId: question.id,
        editingQuestion: null,
      },
    })
  }

  const bankContext = [bank.academicLevelName, bank.subjectName].filter(Boolean).join(' · ')

  return (
    <div className="teacher-reference-page teacher-bank-detail">
      <div className="teacher-bank-detail__heading">
        <div className="teacher-page-title-line">
          <span className="teacher-page-title-icon"><Icon name="bank" size={27} /></span>
          <PageTitle
            title={bank.name}
            subtitle={`${bankContext ? `${bankContext} · ` : ''}${questions.length} ${questions.length === 1 ? 'question' : 'questions'} in this bank`}
          />
        </div>
        <button className="teacher-bank-detail__back" onClick={() => dispatch({ type: 'staff', patch: { section: 'question-banks' } })}>
          <RiArrowLeftLine size={18} aria-hidden="true" /> Back to question banks
        </button>
      </div>
      <QuestionRows questions={questions} onPreview={previewQuestion} />
    </div>
  )
}
