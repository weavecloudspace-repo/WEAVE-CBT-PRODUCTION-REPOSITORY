import { useEffect, useRef, useState } from 'react'
import './question-authoring-workspace.css'

const WIDTH_KEY = 'weave.teacher.aiPanelWidth'
const DEFAULT_WIDTH = 380
const MIN_WIDTH = 300
const MIN_EDITOR_WIDTH = 560
const DIVIDER_WIDTH = 5

function readWidth() {
  try {
    const value = Number(window.localStorage.getItem(WIDTH_KEY))
    return value >= MIN_WIDTH && value <= 640 ? value : DEFAULT_WIDTH
  } catch { return DEFAULT_WIDTH }
}

export function QuestionAuthoringWorkspace({ children, panel, open }) {
  const workspaceRef = useRef(null)
  const dragRef = useRef(null)
  const [width, setWidth] = useState(readWidth)
  const [availableWidth, setAvailableWidth] = useState(1100)
  const [dragging, setDragging] = useState(false)
  // A remembered preference must still fit this shell, including its sidebar.
  // Keep the form wider than the assistant and reserve usable editor space.
  const maximum = Math.max(MIN_WIDTH, Math.floor(Math.min(640, availableWidth * .42, availableWidth - MIN_EDITOR_WIDTH - DIVIDER_WIDTH)))
  const actualWidth = Math.min(width, maximum)

  useEffect(() => {
    const element = workspaceRef.current
    if (!element || typeof ResizeObserver === 'undefined') return undefined
    const observer = new ResizeObserver(([entry]) => setAvailableWidth(entry.contentRect.width))
    observer.observe(element)
    return () => observer.disconnect()
  }, [])

  const resize = (nextWidth) => {
    const next = Math.round(Math.max(MIN_WIDTH, Math.min(maximum, nextWidth)))
    setWidth(next)
    try { window.localStorage.setItem(WIDTH_KEY, String(next)) } catch { /* Resizing works without storage. */ }
  }
  const endDrag = () => { dragRef.current = null; setDragging(false) }
  const startDrag = (event) => {
    if (event.button !== 0) return
    event.preventDefault()
    event.currentTarget.setPointerCapture(event.pointerId)
    dragRef.current = { x: event.clientX, width: actualWidth }
    setDragging(true)
  }
  const moveDrag = (event) => {
    if (dragRef.current) resize(dragRef.current.width + dragRef.current.x - event.clientX)
  }
  const keyResize = (event) => {
    const step = event.shiftKey ? 50 : 20
    const next = { ArrowLeft: actualWidth + step, ArrowRight: actualWidth - step, Home: MIN_WIDTH, End: maximum }[event.key]
    if (next === undefined) return
    event.preventDefault()
    resize(next)
  }

  return <div ref={workspaceRef} className={`question-authoring-workspace${open ? ' is-panel-open' : ''}${dragging ? ' is-resizing' : ''}`} style={{ '--ai-panel-width': `${actualWidth}px` }}>
    <div className="question-authoring-editor">{children}</div>
    {open && <div className="question-authoring-divider" role="separator" tabIndex={0} aria-label="Resize AI panel" aria-orientation="vertical" aria-controls="teacher-ai-panel" aria-valuemin={MIN_WIDTH} aria-valuemax={maximum} aria-valuenow={actualWidth} aria-valuetext={`${actualWidth} pixels wide`} onPointerDown={startDrag} onPointerMove={moveDrag} onPointerUp={endDrag} onPointerCancel={endDrag} onLostPointerCapture={endDrag} onKeyDown={keyResize} onDoubleClick={() => resize(DEFAULT_WIDTH)} />}
    <div id="teacher-ai-panel" className="question-authoring-panel" hidden={!open}>{panel}</div>
  </div>
}
