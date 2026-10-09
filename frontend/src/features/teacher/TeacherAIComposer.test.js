import { describe, expect, it, vi } from 'vitest'

import { handlePromptKeyDown } from './teacherPromptEvents'

function makeEvent({ key = 'Enter', shiftKey = false, isComposing = false } = {}) {
  const requestSubmit = vi.fn()
  const preventDefault = vi.fn()
  return {
    event: {
      key,
      shiftKey,
      nativeEvent: { isComposing },
      preventDefault,
      currentTarget: { form: { requestSubmit } },
    },
    preventDefault,
    requestSubmit,
  }
}

describe('AI prompt keyboard submission', () => {
  it('submits the form when Enter is pressed', () => {
    const { event, preventDefault, requestSubmit } = makeEvent()

    handlePromptKeyDown(event, false)

    expect(preventDefault).toHaveBeenCalledOnce()
    expect(requestSubmit).toHaveBeenCalledOnce()
  })

  it('keeps Shift+Enter available for a new line', () => {
    const { event, preventDefault, requestSubmit } = makeEvent({ shiftKey: true })

    handlePromptKeyDown(event, false)

    expect(preventDefault).not.toHaveBeenCalled()
    expect(requestSubmit).not.toHaveBeenCalled()
  })

  it('does not submit while generation is disabled', () => {
    const { event, preventDefault, requestSubmit } = makeEvent()

    handlePromptKeyDown(event, true)

    expect(preventDefault).toHaveBeenCalledOnce()
    expect(requestSubmit).not.toHaveBeenCalled()
  })

  it('does not intercept Enter during IME composition', () => {
    const { event, preventDefault, requestSubmit } = makeEvent({ isComposing: true })

    handlePromptKeyDown(event, false)

    expect(preventDefault).not.toHaveBeenCalled()
    expect(requestSubmit).not.toHaveBeenCalled()
  })
})
