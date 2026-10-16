import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

describe('student exam question positioning on wide monitors', () => {
  it('centers only the active question paper relative to the full viewport', () => {
    const css = readFileSync('src/features/student/student.css', 'utf8')
    const wideRules = css.match(/\/\* Center the active question paper[\s\S]*?(?=\n@media \(max-width: 900px\))/)?.[0]

    expect(wideRules).toBeDefined()
    expect(wideRules).toMatch(/@media screen and \(min-width: 1600px\)/)
    expect(wideRules).toMatch(/\.premium-exam-shell--session \.premium-exam-content > \.premium-question-paper/)
    expect(wideRules).toMatch(/translate: -129px 0;/)
    expect(wideRules).toMatch(/margin-block: auto;/)
    expect(wideRules).not.toMatch(/\.premium-exam-(?:frame|rail|stage|header|navigation)\s*\{/)
    expect(css).toMatch(/\.premium-exam-frame \{\s*display: grid;\s*grid-template-columns: 258px minmax\(0, 1fr\);/)
  })

  it('preserves the same candidate question, answer and navigation components', () => {
    const source = readFileSync('src/features/student/StudentWorkspace.jsx', 'utf8')
    expect(source).toContain('className="premium-exam-shell premium-exam-shell--session"')
    expect(source).toContain('className="premium-exam-content"')
    expect(source).toContain('className="premium-question-paper"')
    expect(source).toContain('className="premium-exam-navigation"')
    expect(source).toContain('saveAnswer({ question: current')
    expect(source).toContain('Save and next')
  })
})
