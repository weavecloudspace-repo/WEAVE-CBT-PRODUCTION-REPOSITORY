import { describe, expect, it, vi } from 'vitest'

import { scrollRegenerationFormIntoView } from './teacherReviewScroll'

describe('question regeneration review scrolling', () => {
  it('scrolls the regeneration form into view smoothly', () => {
    const scrollIntoView = vi.fn()

    scrollRegenerationFormIntoView({ scrollIntoView })

    expect(scrollIntoView).toHaveBeenCalledWith({ behavior: 'smooth', block: 'end' })
  })

  it('does nothing when the regeneration form is unavailable', () => {
    expect(() => scrollRegenerationFormIntoView(null)).not.toThrow()
  })
})
