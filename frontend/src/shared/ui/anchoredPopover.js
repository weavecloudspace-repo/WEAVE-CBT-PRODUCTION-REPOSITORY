const DEFAULT_VIEWPORT_PADDING = 12
const DEFAULT_GAP = 8

function clamp(value, min, max) {
  return Math.min(Math.max(value, min), max)
}

/**
 * Position a fixed popover next to its trigger without letting it drift into
 * unrelated page chrome. Prefer the trigger's right side, fall back to the
 * left, and only overlap the trigger horizontally when neither side can fit.
 *
 * The vertical position stays visually anchored to the trigger and is clamped
 * inside the viewport. The popover owns its own scrolling when content is
 * taller than the available viewport height.
 */
export function getAnchoredPopoverPosition(trigger, options = {}) {
  if (!trigger || typeof window === 'undefined') {
    return {
      placement: 'right',
      style: {
        position: 'fixed',
        left: DEFAULT_VIEWPORT_PADDING,
        top: DEFAULT_VIEWPORT_PADDING,
        zIndex: 1250,
      },
    }
  }

  const {
    width: preferredWidth = 320,
    maxHeight: preferredMaxHeight = 420,
    gap = DEFAULT_GAP,
    viewportPadding = DEFAULT_VIEWPORT_PADDING,
    verticalOffset = -4,
  } = options

  const rect = trigger.getBoundingClientRect()
  const viewportWidth = window.innerWidth
  const viewportHeight = window.innerHeight
  const availableViewportWidth = Math.max(160, viewportWidth - viewportPadding * 2)
  const width = Math.min(preferredWidth, availableViewportWidth)
  const maxHeight = Math.min(
    preferredMaxHeight,
    Math.max(96, viewportHeight - viewportPadding * 2),
  )

  const rightCandidate = rect.right + gap
  const leftCandidate = rect.left - gap - width
  const fitsRight = rightCandidate + width <= viewportWidth - viewportPadding
  const fitsLeft = leftCandidate >= viewportPadding

  let placement = 'right'
  let left = rightCandidate

  if (!fitsRight && fitsLeft) {
    placement = 'left'
    left = leftCandidate
  } else if (!fitsRight && !fitsLeft) {
    placement = 'overlap'
    left = clamp(
      rect.right - width,
      viewportPadding,
      Math.max(viewportPadding, viewportWidth - width - viewportPadding),
    )
  }

  const maxTop = Math.max(viewportPadding, viewportHeight - maxHeight - viewportPadding)
  const top = clamp(rect.top + verticalOffset, viewportPadding, maxTop)

  return {
    placement,
    style: {
      position: 'fixed',
      boxSizing: 'border-box',
      width,
      maxHeight,
      overflowY: 'auto',
      overscrollBehavior: 'contain',
      zIndex: 1250,
      left,
      top,
      right: 'auto',
      bottom: 'auto',
    },
  }
}
