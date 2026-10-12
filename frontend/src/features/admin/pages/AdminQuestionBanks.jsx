import { useEffect, useMemo, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import {
  RiArchiveLine,
  RiArrowLeftLine,
  RiArrowRightLine,
  RiDeleteBinLine,
  RiEdit2Line,
  RiMore2Line,
  RiRefreshLine,
  RiSearchLine,
} from '@remixicon/react'
import { Icon } from '../../../shared/icons/Icon'
import { getAnchoredPopoverPosition } from '../../../shared/ui/anchoredPopover'
import { Notice, PageTitle, SelectControl, StatusBadge } from '../../../shared/ui'
import { QuestionRows } from '../../teacher/components'

export function AdminQuestionBanksPage({ adminData, gateway, onNavigate, createRequested = false, onCreateHandled }) {
  const [query, setQuery] = useState('')
  const [localEditor, setEditor] = useState(null)
  const editor = createRequested ? { mode: 'create', bank: null } : localEditor
  const [menuBankId, setMenuBankId] = useState(null)
  const [menuPosition, setMenuPosition] = useState(null)
  const [pendingAction, setPendingAction] = useState(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const menuRef = useRef(null)


  const closeEditor = () => {
    setEditor(null)
    if (createRequested) onCreateHandled?.()
  }

  const closeMenu = () => {
    setMenuBankId(null)
    setMenuPosition(null)
  }

  useEffect(() => {
    if (!menuBankId) return undefined
    const close = (event) => {
      if (event.type === 'keydown' && event.key === 'Escape') closeMenu()
      if (
        event.type === 'pointerdown' &&
        !menuRef.current?.contains(event.target) &&
        !event.target.closest?.('.admin-bank-card__menu-trigger')
      ) closeMenu()
    }
    const closeOnViewportChange = () => closeMenu()
    document.addEventListener('pointerdown', close)
    document.addEventListener('keydown', close)
    window.addEventListener('resize', closeOnViewportChange)
    window.addEventListener('scroll', closeOnViewportChange, true)
    return () => {
      document.removeEventListener('pointerdown', close)
      document.removeEventListener('keydown', close)
      window.removeEventListener('resize', closeOnViewportChange)
      window.removeEventListener('scroll', closeOnViewportChange, true)
    }
  }, [menuBankId])

  const banks = useMemo(() => {
    const needle = query.trim().toLowerCase()
    if (!needle) return adminData.banks
    return adminData.banks.filter((bank) => `${bank.name} ${bank.description || ''} ${bank.academicLevelName || ''} ${bank.subjectName || ''}`.toLowerCase().includes(needle))
  }, [adminData.banks, query])

  const toggleBankMenu = (bankId, trigger) => {
    if (menuBankId === bankId) return closeMenu()
    setMenuPosition(getAnchoredPopoverPosition(trigger, { width: 300, maxHeight: 320 }))
    setMenuBankId(bankId)
  }

  const requestLifecycle = (bank, action) => {
    if (action === 'delete' && bank.canDelete !== true) return
    closeMenu()
    setError('')
    setPendingAction({ bank, action })
  }

  const confirmLifecycle = async () => {
    if (!pendingAction) return
    const { bank, action } = pendingAction
    setBusy(true)
    setError('')
    try {
      if (action === 'archive') await gateway.questions.archiveQuestionBank(bank.id)
      if (action === 'reactivate') await gateway.questions.reactivateQuestionBank(bank.id)
      if (action === 'delete') await gateway.questions.deleteEmptyQuestionBank(bank.id)
      await adminData.refresh()
      setPendingAction(null)
    } catch (requestError) {
      setError(requestError.userMessage || `Weave could not ${action} this question bank.`)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="teacher-reference-page admin-banks-page">
      <div className="teacher-page-heading teacher-page-heading--with-search admin-bank-heading">
        <div>
          <div className="teacher-page-title-line">
            <span className="teacher-page-title-icon"><Icon name="bank" size={27} /></span>
            <h1>Question Banks</h1>
          </div>
          <p>Manage every question bank synchronized to this school CBT server.</p>
        </div>
        <div className="admin-bank-heading__actions">
          <label className="teacher-search-control">
            <RiSearchLine size={17} aria-hidden="true" />
            <input aria-label="Search question banks" type="search" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search banks, levels or subjects..." />
          </label>
          <button className="teacher-primary-action" type="button" onClick={() => setEditor({ mode: 'create', bank: null })}>
            <Icon name="plus" size={18} /> Create Bank
          </button>
        </div>
      </div>

      {adminData.error && <Notice tone="danger">{adminData.error}</Notice>}
      {adminData.warning && <Notice tone="warning">{adminData.warning}</Notice>}
      {error && !pendingAction && <Notice tone="danger">{error}</Notice>}

      {adminData.loading && <div className="teacher-page-loading">Loading school question banks…</div>}
      {!adminData.loading && adminData.banks.length === 0 && (
        <div className="teacher-reference-empty teacher-reference-empty--large">
          <Icon name="bank" size={30} />
          <div><strong>No question banks yet</strong><p>Create a bank for a curriculum subject before questions can be authored.</p></div>
          <button type="button" onClick={() => setEditor({ mode: 'create', bank: null })}>Create question bank</button>
        </div>
      )}

      <section className="teacher-bank-grid" aria-label="School question banks">
        {banks.map((bank) => (
          <article key={bank.id} className={`teacher-bank-card admin-bank-card${bank.status === 'Archived' ? ' is-archived' : ''}`}>
            <div className="admin-bank-card__topline">
              <span className="teacher-bank-card__icon"><Icon name="bank" size={22} /></span>
              <div className="admin-bank-card__menu">
                <button type="button" className="admin-bank-card__menu-trigger" aria-label={`Manage ${bank.name}`} aria-expanded={menuBankId === bank.id} onClick={(event) => toggleBankMenu(bank.id, event.currentTarget)}><RiMore2Line size={20} /></button>
                {menuBankId === bank.id && menuPosition && typeof document !== 'undefined' && createPortal(
                  <div ref={menuRef} className="admin-bank-card__popover" role="menu" data-placement={menuPosition.placement} style={menuPosition.style}>
                    <button type="button" role="menuitem" onClick={() => { closeMenu(); setEditor({ mode: 'edit', bank }) }}><RiEdit2Line size={17} /><span><strong>Edit bank</strong><small>Change its name and description; empty banks may also move level or subject.</small></span></button>
                    <button type="button" role="menuitem" onClick={() => requestLifecycle(bank, bank.status === 'Archived' ? 'reactivate' : 'archive')}>
                      {bank.status === 'Archived' ? <RiRefreshLine size={17} /> : <RiArchiveLine size={17} />}
                      <span><strong>{bank.status === 'Archived' ? 'Reactivate bank' : 'Archive bank'}</strong><small>{bank.status === 'Archived' ? 'Return it to active authoring.' : 'Keep its history but stop authoring.'}</small></span>
                    </button>
                    {bank.canDelete === true && (<button type="button" role="menuitem" className="is-danger" onClick={() => requestLifecycle(bank, 'delete')}><RiDeleteBinLine size={17} /><span><strong>Delete empty bank</strong><small>Permanently remove this empty bank.</small></span></button>)}
                  </div>,
                  document.body,
                )}
              </div>
            </div>
            <div className="teacher-bank-card__body">
              <div className="admin-bank-card__subject">{bank.academicLevelName ? `${bank.academicLevelName} · ` : ''}{bank.subjectName}{bank.subjectCode ? ` · ${bank.subjectCode}` : ''}</div>
              <h2>{bank.name}</h2>
              <p>{bank.description || 'School question bank available for examination authoring.'}</p>
              <div className="teacher-bank-card__meta">
                <span>{bank.count} {bank.count === 1 ? 'question' : 'questions'} · {bank.activeQuestionCount} active</span>
                <StatusBadge tone={bank.status === 'Ready' ? 'success' : 'warning'}>{bank.status}</StatusBadge>
              </div>
            </div>
            <button type="button" className="teacher-bank-card__action" onClick={() => onNavigate('bank-detail', { selectedBankId: bank.id })}>
              View Questions <RiArrowRightLine size={16} aria-hidden="true" />
            </button>
          </article>
        ))}
      </section>

      {!adminData.loading && adminData.banks.length > 0 && banks.length === 0 && (
        <div className="teacher-reference-empty teacher-reference-empty--compact"><div><strong>No matching banks</strong><p>Try a different bank, level, or subject name.</p></div></div>
      )}

      {editor && <BankEditorModal editor={editor} subjects={adminData.subjects} gateway={gateway} onClose={closeEditor} onSaved={async () => { closeEditor(); await adminData.refresh() }} />}
      {pendingAction && <BankLifecycleModal pending={pendingAction} busy={busy} error={error} onCancel={() => { if (!busy) { setPendingAction(null); setError('') } }} onConfirm={confirmLifecycle} />}
    </div>
  )
}

export function AdminBankDetailPage({ state, adminData, onNavigate }) {
  const bank = adminData.banks.find((item) => item.id === state.staff.selectedBankId) || adminData.banks[0]
  const questions = bank ? adminData.questions.filter((question) => question.bankId === bank.id) : []

  if (!bank) return <><PageTitle title="Question Bank" subtitle="No bank selected." /><Notice>No question banks are available on this server.</Notice></>

  const bankContext = `${bank.academicLevelName ? `${bank.academicLevelName} · ` : ''}${bank.subjectName}`

  return (
    <div className="teacher-reference-page teacher-bank-detail admin-bank-detail">
      <div className="teacher-bank-detail__heading">
        <div>
          <div className="teacher-page-title-line">
            <span className="teacher-page-title-icon"><Icon name="bank" size={27} /></span>
            <PageTitle title={bank.name} subtitle={`${bankContext} · ${questions.length} ${questions.length === 1 ? 'question' : 'questions'}`} />
          </div>
          <StatusBadge tone={bank.status === 'Ready' ? 'success' : 'warning'}>{bank.status}</StatusBadge>
        </div>
        <div className="admin-bank-detail__actions">
          <button className="teacher-secondary-action" type="button" onClick={() => onNavigate('question-banks')}><RiArrowLeftLine size={17} /> Back to banks</button>
          <button className="teacher-primary-action" type="button" disabled={bank.status === 'Archived'} onClick={() => onNavigate('create-question', { selectedBankId: bank.id })}><Icon name="plus" size={17} /> Add Question</button>
        </div>
      </div>
      <QuestionRows questions={questions} onPreview={(question) => onNavigate('preview-question', { selectedBankId: bank.id, selectedQuestionId: question.id })} />
      {!questions.length && !adminData.loading && (
        <div className="teacher-reference-empty teacher-reference-empty--compact"><div><strong>This bank is empty</strong><p>Add the first question or return to the school bank list.</p></div></div>
      )}
    </div>
  )
}

function BankEditorModal({ editor, subjects, gateway, onClose, onSaved }) {
  const editing = editor.mode === 'edit'
  const subjectLocked = editing && Number(editor.bank?.count || 0) > 0
  const levels = buildAcademicLevels(subjects)
  const existingSubject = subjects.find((subject) => subject.id === editor.bank?.curriculumSubjectId)
  const initialLevelId = existingSubject?.academicLevelId || levels[0]?.id || ''
  const initialSubjectId = existingSubject?.id || subjects.find((subject) => subject.academicLevelId === initialLevelId)?.id || ''

  const [levelId, setLevelId] = useState(initialLevelId)
  const [subjectId, setSubjectId] = useState(initialSubjectId)
  const [name, setName] = useState(editor.bank?.name || '')
  const [description, setDescription] = useState(editor.bank?.description || '')
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')

  const subjectsForLevel = useMemo(
    () => subjects.filter((subject) => subject.academicLevelId === levelId),
    [levelId, subjects],
  )

  const levelOptions = levels.map((level) => ({
    value: level.id,
    label: level.name,
    description: level.category ? humanize(level.category) : undefined,
  }))
  const subjectOptions = subjectsForLevel.map((subject) => ({
    value: subject.id,
    label: subject.name,
    description: subject.code || undefined,
  }))
  const selectedLevel = levels.find((level) => level.id === levelId)
  const selectedSubject = subjects.find((subject) => subject.id === subjectId)

  const changeLevel = (nextLevelId) => {
    setLevelId(nextLevelId)
    const firstSubject = subjects.find((subject) => subject.academicLevelId === nextLevelId)
    setSubjectId(firstSubject?.id || '')
    setError('')
  }

  const submit = async (event) => {
    event.preventDefault()
    setError('')
    if (!levelId) return setError('Choose an academic level before selecting a subject.')
    if (!subjectId || !name.trim()) return setError('Choose a subject in this level and enter a bank name.')
    setSaving(true)
    try {
      if (editing) {
        await gateway.questions.updateQuestionBank(editor.bank.id, { name: name.trim(), description: description.trim() || null, curriculum_subject_id: subjectId })
      } else {
        await gateway.questions.createQuestionBank(subjectId, { name: name.trim(), description: description.trim() || null })
      }
      await onSaved()
    } catch (requestError) {
      setError(requestError.userMessage || `Weave could not ${editing ? 'update' : 'create'} this question bank.`)
    } finally {
      setSaving(false)
    }
  }

  const bankNameExample = [selectedLevel?.name, selectedSubject?.name].filter(Boolean).join(' ') || 'JSS1 English Language'

  return createPortal(
    <div className="admin-modal-backdrop" onMouseDown={(event) => { if (event.currentTarget === event.target && !saving) onClose() }}>
      <form className="admin-bank-editor-modal" onSubmit={submit} role="dialog" aria-modal="true" aria-labelledby="admin-bank-editor-title">
        <div className="admin-bank-editor-modal__head"><span><Icon name="bank" size={22} /></span><div><h2 id="admin-bank-editor-title">{editing ? 'Edit question bank' : 'Create question bank'}</h2><p>{editing ? 'Update the school bank metadata without changing its questions.' : 'Choose the academic level first, then select a subject from that level’s curriculum.'}</p></div></div>
        {error && <Notice tone="danger">{error}</Notice>}

        <label className="admin-modal-field">
          <span>Academic level</span>
          <SelectControl
            label="Academic level"
            value={levelId}
            options={levelOptions}
            onChange={changeLevel}
            disabled={subjectLocked}
            placeholder="Choose a level"
          />
          {!subjectLocked && <small>Subjects are filtered to the curriculum for the selected level.</small>}
        </label>

        <label className="admin-modal-field">
          <span>Subject</span>
          <SelectControl
            label="Subject"
            value={subjectId}
            options={subjectOptions}
            onChange={(value) => { setSubjectId(value); setError('') }}
            disabled={subjectLocked || !levelId || subjectOptions.length === 0}
            placeholder={levelId ? 'Choose a subject' : 'Choose a level first'}
          />
          {subjectLocked && <small>This bank already contains questions, so its academic level and subject are locked.</small>}
          {!subjectLocked && levelId && subjectOptions.length === 0 && <small>No active curriculum subjects are available for this level.</small>}
        </label>

        <label className="admin-modal-field"><span>Bank name</span><input value={name} maxLength={255} onChange={(event) => setName(event.target.value)} placeholder={`e.g. ${bankNameExample}`} /></label>
        <label className="admin-modal-field"><span>Description <small>(optional)</small></span><textarea rows="4" value={description} onChange={(event) => setDescription(event.target.value)} placeholder="Describe the scope of questions expected in this bank." /></label>
        <div className="admin-modal-actions"><button type="button" className="teacher-secondary-action" disabled={saving} onClick={onClose}>Cancel</button><button type="submit" className="teacher-primary-action" disabled={saving || !levels.length || !subjectId}>{saving ? 'Saving…' : editing ? 'Save changes' : 'Create bank'}</button></div>
      </form>
    </div>,
    document.body,
  )
}

function BankLifecycleModal({ pending, busy, error, onCancel, onConfirm }) {
  const destructive = pending.action === 'delete'
  const copy = pending.action === 'archive'
    ? ['Archive this question bank?', 'The bank and its questions remain preserved, but new authoring from it stops until reactivated.', 'Archive bank']
    : pending.action === 'reactivate'
      ? ['Reactivate this question bank?', 'The bank will return to active authoring and can be used by authorized staff again.', 'Reactivate bank']
      : ['Delete this empty question bank?', 'Permanent deletion is only supported for banks that contain no questions.', 'Delete bank']

  return createPortal(
    <div className="admin-modal-backdrop" onMouseDown={(event) => { if (event.currentTarget === event.target && !busy) onCancel() }}>
      <section className={`admin-bank-lifecycle-modal${destructive ? ' is-danger' : ''}`} role="alertdialog" aria-modal="true">
        <div className="admin-bank-editor-modal__head"><span>{destructive ? <RiDeleteBinLine size={22} /> : pending.action === 'archive' ? <RiArchiveLine size={22} /> : <RiRefreshLine size={22} />}</span><div><h2>{copy[0]}</h2><p>{copy[1]}</p></div></div>
        <div className="admin-bank-lifecycle-modal__bank"><span>Question bank</span><strong>{pending.bank.name}</strong><small>{pending.bank.academicLevelName ? `${pending.bank.academicLevelName} · ` : ''}{pending.bank.subjectName} · {pending.bank.count} questions</small></div>
        {error && <Notice tone="danger">{error}</Notice>}
        <div className="admin-modal-actions"><button type="button" className="teacher-secondary-action" disabled={busy} onClick={onCancel}>Cancel</button><button type="button" className={`teacher-primary-action${destructive ? ' admin-danger-action' : ''}`} disabled={busy} onClick={onConfirm}>{busy ? 'Working…' : copy[2]}</button></div>
      </section>
    </div>,
    document.body,
  )
}

function buildAcademicLevels(subjects) {
  const levels = new Map()
  subjects.forEach((subject) => {
    if (!subject.academicLevelId || !subject.academicLevelName) return
    if (!levels.has(subject.academicLevelId)) {
      levels.set(subject.academicLevelId, {
        id: subject.academicLevelId,
        name: subject.academicLevelName,
        category: subject.academicLevelCategory,
        position: subject.academicLevelPosition ?? 0,
      })
    }
  })
  return [...levels.values()].sort((left, right) => left.position - right.position || left.name.localeCompare(right.name))
}

function humanize(value) {
  return String(value || '').replaceAll('_', ' ').replace(/\b\w/g, (letter) => letter.toUpperCase())
}
