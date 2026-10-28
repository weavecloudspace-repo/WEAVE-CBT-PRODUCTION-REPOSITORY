// Mathematics is normalized for display only; question text remains intact in storage.
const MATH_PATTERN = /(\\\[[\s\S]*?\\\]|\\\([\s\S]*?\\\)|\$\$[\s\S]*?\$\$|\$[^\n$]+?\$|\\(?:dfrac|tfrac|frac)\{[^{}]*\}\{[^{}]*\}|\\sqrt(?:\[[^\]]+\])?\{[^{}]*\}|\\(?:sin|cos|tan|log|ln|lim)(?:_\{?[\w\d]+\}?)?(?:\s*\([^()]*\)|\s*\d+(?:\.\d+)?(?:\s*\^?\s*\\circ)?)?|\\(?:sum|int|pi|theta|alpha|beta)(?:_\{?[\w\d]+\}?)?)/g
const MATH_SIGNAL = /\\[a-zA-Z]+|[=+*/^_{}]|[a-zA-Z]\s*[-+]\s*\d/

export function splitMathSegments(value) {
  const input = String(value || '')
  const tokens = []
  let last = 0
  for (const match of input.matchAll(MATH_PATTERN)) {
    const raw = match[0]
    const pos = match.index
    if (pos > last) tokens.push({ text: input.slice(last, pos), math: false })
    let latex = raw
    let display = false
    if (raw.startsWith('\\[')) { latex = raw.slice(2, -2); display = true }
    else if (raw.startsWith('\\(')) latex = raw.slice(2, -2)
    else if (raw.startsWith('$$')) { latex = raw.slice(2, -2); display = true }
    else if (raw.startsWith('$')) {
      latex = raw.slice(1, -1)
      // Do not mistake currency such as "$10 and $20" for mathematics.
      if (!MATH_SIGNAL.test(latex) && !/^[a-zA-Z]$/.test(latex)) {
        tokens.push({ text: raw, math: false })
        last = pos + raw.length
        continue
      }
    }
    tokens.push({ text: latex, math: true, display })
    last = pos + raw.length
  }
  if (last < input.length) tokens.push({ text: input.slice(last), math: false })
  return tokens
}

export function normalizeMathText(value) {
  return splitMathSegments(value).map((part) => part.math
    ? (part.display ? '\\[' + part.text + '\\]' : '\\(' + part.text + '\\)')
    : part.text).join('')
}

// Select an existing inline or display equation when the cursor is inside it.
export function equationAtCursor(value, cursor) {
  const input = String(value || '')
  const pattern = /(\\\[[\s\S]*?\\\]|\\\([\s\S]*?\\\))/g
  for (const match of input.matchAll(pattern)) {
    const end = match.index + match[0].length
    if (cursor >= match.index && cursor <= end) {
      return { start: match.index, end, latex: match[0].slice(2, -2), display: match[0].startsWith('\\[') }
    }
  }
  return null
}
