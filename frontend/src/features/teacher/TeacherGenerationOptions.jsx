import { useEffect, useId, useRef, useState } from 'react'
import { SelectControl } from '../../shared/ui'
import './teacher-selects.css'
import { RiArrowDownSLine, RiRefreshLine, RiSettings3Line } from '@remixicon/react'

const difficulties = ['easy', 'medium', 'difficult']

export function TeacherGenerationOptions({ count, setCount, difficulty, setDifficulty, type, setType, visuals, setVisuals, disabled, onOpen }) {
  const [open, setOpen] = useState(false)
  const root = useRef(null)
  const trigger = useRef(null)
  const slider = useRef(null)
  const id = useId()
  useEffect(() => {
    if (!open) return undefined
    slider.current?.focus()
    const dismiss = (event) => {
      if (event.type === 'keydown') {
        if (event.key !== 'Escape' || root.current?.querySelector('[role=combobox][aria-expanded=true]')) return
        setOpen(false)
        trigger.current?.focus()
      } else if (!root.current?.contains(event.target)) setOpen(false)
    }
    const form = root.current?.closest('form')
    const closeOnSubmit = () => setOpen(false)
    form?.addEventListener('submit', closeOnSubmit)
    document.addEventListener('pointerdown', dismiss)
    document.addEventListener('keydown', dismiss)
    return () => {
      form?.removeEventListener('submit', closeOnSubmit)
      document.removeEventListener('pointerdown', dismiss)
      document.removeEventListener('keydown', dismiss)
    }
  }, [open])
  const reset = () => {
    setCount(5)
    setDifficulty('medium')
    setType('single_choice')
    setVisuals('text_only')
  }
  return <div className="teacher-generation-options" ref={root} onBlur={(event) => {
    if (!event.currentTarget.contains(event.relatedTarget)) setOpen(false)
  }}>
    <button ref={trigger} type="button" className="teacher-generation-options__trigger" disabled={disabled} aria-expanded={open && !disabled} aria-controls={id} aria-haspopup="dialog" aria-label={`Generation options: ${count} questions, ${difficulty} difficulty`} onClick={() => { if (!open) onOpen?.(); setOpen(!open) }}>
      <RiSettings3Line size={16} /><span>{count} questions</span><span className="teacher-generation-options__difficulty">{difficulty}</span><RiArrowDownSLine size={15} />
    </button>
    {open && !disabled && <div id={id} role="dialog" aria-label="Generation options" className="teacher-generation-options__popover">
      <header><div><strong>{difficulty}</strong><span>Question difficulty</span></div><button type="button" className="teacher-ai-icon-button" aria-label="Reset generation options" title="Reset to defaults" onClick={reset}><RiRefreshLine size={17} /></button></header>
      <div className="teacher-generation-options__range">
        <input ref={slider} aria-label="Difficulty" type="range" min="0" max="2" step="1" value={difficulties.indexOf(difficulty)} aria-valuetext={difficulty} onChange={(event) => setDifficulty(difficulties[Number(event.target.value)])} />
        <div aria-hidden="true"><span>Easy</span><span>Medium</span><span>Difficult</span></div>
      </div>
      <label className="teacher-generation-options__count">Questions<input aria-label="Question count" type="number" min="1" max="50" step="1" required value={count} onFocus={(event) => event.target.select()} onChange={(event) => setCount(event.target.value)} onBlur={(event) => { if (!event.target.value) setCount(5) }} /></label>
      <div className="teacher-generation-options__format teacher-generation-options__field">
        <span>Question format</span>
        <SelectControl label="Question format" value={visuals} onChange={setVisuals} options={[[ 'text_only', 'Text only' ], [ 'auto', 'Allow images' ]]} />
        <p>{visuals === 'text_only' ? 'Questions and answers will use text only.' : 'Images may be included where helpful; they are not guaranteed.'}</p>
      </div>
      <div className="teacher-generation-options__fields">
        <div className="teacher-generation-options__field"><span>Answer type</span><SelectControl label="Answer type" value={type} onChange={setType} options={[['single_choice', 'Single choice'], ['multiple_choice', 'Multiple choice'], ['mixed', 'Mixed']]} /></div>
        
      </div>
    </div>}
  </div>
}
