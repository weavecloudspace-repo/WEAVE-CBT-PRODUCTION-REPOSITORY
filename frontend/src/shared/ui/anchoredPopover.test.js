import { afterEach, describe, expect, it } from 'vitest'
import { getAnchoredPopoverPosition } from './anchoredPopover'

const originalWidth = window.innerWidth
const originalHeight = window.innerHeight

afterEach(() => {
  Object.defineProperty(window, 'innerWidth', { configurable: true, value: originalWidth })
  Object.defineProperty(window, 'innerHeight', { configurable: true, value: originalHeight })
})

function trigger(rect) {
  return { getBoundingClientRect: () => rect }
}

function viewport(width, height) {
  Object.defineProperty(window, 'innerWidth', { configurable: true, value: width })
  Object.defineProperty(window, 'innerHeight', { configurable: true, value: height })
}

describe('getAnchoredPopoverPosition', () => {
  it('opens to the right when there is natural room beside the trigger', () => {
    viewport(1200, 700)
    const result = getAnchoredPopoverPosition(trigger({ left: 360, right: 394, top: 260, bottom: 294 }), { width: 330 })

    expect(result.placement).toBe('right')
    expect(result.style.left).toBe(402)
    expect(result.style.top).toBe(256)
    expect(result.style.position).toBe('fixed')
  })

  it('opens to the left near the right viewport edge', () => {
    viewport(1200, 700)
    const result = getAnchoredPopoverPosition(trigger({ left: 1110, right: 1146, top: 340, bottom: 376 }), { width: 320 })

    expect(result.placement).toBe('left')
    expect(result.style.left).toBe(782)
  })

  it('clamps tall menus inside the viewport instead of pushing them off-screen', () => {
    viewport(900, 520)
    const result = getAnchoredPopoverPosition(trigger({ left: 420, right: 454, top: 490, bottom: 524 }), { width: 320, maxHeight: 400 })

    expect(result.style.maxHeight).toBe(400)
    expect(result.style.top).toBe(108)
    expect(result.style.overflowY).toBe('auto')
  })

  it('falls back to a viewport-safe overlap on narrow screens', () => {
    viewport(280, 500)
    const result = getAnchoredPopoverPosition(trigger({ left: 120, right: 154, top: 80, bottom: 114 }), { width: 320 })

    expect(result.placement).toBe('overlap')
    expect(result.style.width).toBe(256)
    expect(result.style.left).toBe(12)
  })
})
