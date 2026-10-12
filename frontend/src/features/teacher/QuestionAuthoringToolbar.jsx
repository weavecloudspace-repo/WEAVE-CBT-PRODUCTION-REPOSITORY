import { useEffect, useRef } from 'react'
import { RiArrowDownSLine, RiArrowLeftLine, RiEyeLine, RiFileList3Line, RiSave3Line } from '@remixicon/react'

export function QuestionAuthoringToolbar({ aiOpen, onToggleAI, onBack, onPreview, onSave, busy }) {
  const menuRef = useRef(null)
  useEffect(() => {
    const closeOutside = (event) => {
      if (!menuRef.current?.contains(event.target) && menuRef.current) menuRef.current.open = false
    }
    document.addEventListener('pointerdown', closeOutside)
    return () => document.removeEventListener('pointerdown', closeOutside)
  }, [])
  return <header className="question-authoring-toolbar" aria-label="Question editor actions">
    <button className="question-authoring-back" type="button" aria-label="Back to questions" disabled={busy} onClick={onBack}><RiArrowLeftLine size={18} /><span>Questions</span></button>
    <div className="question-authoring-toolbar__actions">
      <button className="question-authoring-preview" type="button" aria-label="Preview question" title="Preview question" disabled={busy} onClick={onPreview}><RiEyeLine size={19} /><span>Preview</span></button>
      <div className="question-authoring-save-group">
        <button className="teacher-primary-action" type="button" disabled={busy} onClick={() => onSave(true)}><RiSave3Line size={17} /><span>{busy ? 'Saving…' : 'Save & create another'}</span></button>
        <details ref={menuRef} className="question-authoring-save-menu" onKeyDown={(event) => { if (event.key === 'Escape') { event.currentTarget.open = false; event.currentTarget.querySelector('summary')?.focus() } }} onBlur={(event) => { if (!event.currentTarget.contains(event.relatedTarget)) event.currentTarget.open = false }}>
          <summary aria-label="More save options" aria-disabled={busy} onClick={(event) => { if (busy) event.preventDefault() }}><RiArrowDownSLine size={18} /></summary>
          <div className="question-authoring-save-menu__items"><button type="button" disabled={busy} onClick={() => { menuRef.current.open = false; onSave(false) }}>Save question</button></div>
        </details>
      </div>
    </div>
    <div className="question-authoring-toolbar__ai"><button className="teacher-ai-toggle" type="button" aria-label={aiOpen ? 'Close question generation' : 'Open question generation'} title={aiOpen ? 'Close question generation' : 'Generate questions'} aria-expanded={aiOpen} aria-controls="teacher-ai-panel" onClick={onToggleAI}><RiFileList3Line size={21} /></button></div>
  </header>
}
