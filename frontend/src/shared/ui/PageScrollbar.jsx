import { useEffect, useRef, useState } from 'react'

const MIN_THUMB_HEIGHT = 56

export function PageScrollbar() {
  const trackRef = useRef(null)
  const thumbRef = useRef(null)
  const metricsRef = useRef({ maxScroll: 0, maxThumbTop: 0, thumbHeight: MIN_THUMB_HEIGHT })
  const dragRef = useRef(null)
  const [visible, setVisible] = useState(false)
  const [value, setValue] = useState(0)

  useEffect(() => {
    let frame = 0

    const sync = () => {
      cancelAnimationFrame(frame)
      frame = requestAnimationFrame(() => {
        const track = trackRef.current
        const thumb = thumbRef.current
        if (!track || !thumb) return

        const root = document.documentElement
        const body = document.body
        const viewportHeight = window.innerHeight
        const scrollHeight = Math.max(root.scrollHeight, body?.scrollHeight || 0)
        const maxScroll = Math.max(0, scrollHeight - viewportHeight)
        const trackHeight = track.clientHeight
        const thumbHeight = maxScroll > 0
          ? Math.min(trackHeight, Math.max(MIN_THUMB_HEIGHT, (viewportHeight / scrollHeight) * trackHeight))
          : trackHeight
        const maxThumbTop = Math.max(0, trackHeight - thumbHeight)
        const scrollTop = Math.min(maxScroll, Math.max(0, window.scrollY || root.scrollTop || 0))
        const ratio = maxScroll > 0 ? scrollTop / maxScroll : 0
        const thumbTop = ratio * maxThumbTop

        metricsRef.current = { maxScroll, maxThumbTop, thumbHeight }
        thumb.style.height = `${thumbHeight}px`
        thumb.style.transform = `translateY(${thumbTop}px)`
        setVisible(maxScroll > 1)
        setValue(Math.round(ratio * 100))
      })
    }

    sync()
    window.addEventListener('scroll', sync, { passive: true })
    window.addEventListener('resize', sync)

    const observer = typeof ResizeObserver === 'undefined' ? null : new ResizeObserver(sync)
    observer?.observe(document.documentElement)
    if (document.body) observer?.observe(document.body)

    return () => {
      cancelAnimationFrame(frame)
      window.removeEventListener('scroll', sync)
      window.removeEventListener('resize', sync)
      observer?.disconnect()
    }
  }, [])

  const scrollToPointer = (clientY, smooth = false) => {
    const track = trackRef.current
    if (!track) return
    const { maxScroll, maxThumbTop, thumbHeight } = metricsRef.current
    if (!maxScroll || !maxThumbTop) return

    const rect = track.getBoundingClientRect()
    const thumbTop = Math.min(maxThumbTop, Math.max(0, clientY - rect.top - thumbHeight / 2))
    window.scrollTo({ top: (thumbTop / maxThumbTop) * maxScroll, behavior: smooth ? 'smooth' : 'auto' })
  }

  const onTrackPointerDown = (event) => {
    if (event.target === thumbRef.current) return
    scrollToPointer(event.clientY, true)
  }

  const onThumbPointerDown = (event) => {
    event.preventDefault()
    const { maxScroll, maxThumbTop } = metricsRef.current
    if (!maxScroll || !maxThumbTop) return
    dragRef.current = { startY: event.clientY, startScroll: window.scrollY }
    event.currentTarget.setPointerCapture(event.pointerId)
  }

  const onThumbPointerMove = (event) => {
    if (!dragRef.current) return
    const { maxScroll, maxThumbTop } = metricsRef.current
    const delta = event.clientY - dragRef.current.startY
    const next = dragRef.current.startScroll + (delta / maxThumbTop) * maxScroll
    window.scrollTo({ top: Math.min(maxScroll, Math.max(0, next)), behavior: 'auto' })
  }

  const stopDragging = (event) => {
    dragRef.current = null
    if (event.currentTarget.hasPointerCapture?.(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId)
    }
  }

  const onKeyDown = (event) => {
    const maxScroll = metricsRef.current.maxScroll
    if (!maxScroll) return
    const step = Math.max(60, window.innerHeight * 0.12)
    const page = window.innerHeight * 0.8
    let next = null

    if (event.key === 'ArrowDown') next = window.scrollY + step
    if (event.key === 'ArrowUp') next = window.scrollY - step
    if (event.key === 'PageDown') next = window.scrollY + page
    if (event.key === 'PageUp') next = window.scrollY - page
    if (event.key === 'Home') next = 0
    if (event.key === 'End') next = maxScroll
    if (next === null) return

    event.preventDefault()
    window.scrollTo({ top: Math.min(maxScroll, Math.max(0, next)), behavior: 'smooth' })
  }

  return (
    <div
      ref={trackRef}
      className={`page-scrollbar${visible ? ' is-visible' : ''}`}
      role="scrollbar"
      aria-label="Page scrollbar"
      aria-orientation="vertical"
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={value}
      tabIndex={visible ? 0 : -1}
      onPointerDown={onTrackPointerDown}
      onKeyDown={onKeyDown}
    >
      <div
        ref={thumbRef}
        className="page-scrollbar__thumb"
        onPointerDown={onThumbPointerDown}
        onPointerMove={onThumbPointerMove}
        onPointerUp={stopDragging}
        onPointerCancel={stopDragging}
      />
    </div>
  )
}
