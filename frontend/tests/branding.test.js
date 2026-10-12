import { describe, expect, it } from 'vitest'

import {
  DEFAULT_LIGHT_TOKENS,
  buildBrandingThemeStyle,
  normalizeBranding,
} from '../src/app/theme/branding'

describe('tenant branding adapter', () => {
  it('keeps Weave blue as the pre-sync default', () => {
    expect(DEFAULT_LIGHT_TOKENS['--color-primary']).toBe('29 78 216')
  })

  it('maps synced semantic tokens into existing UI color variables', () => {
    const style = buildBrandingThemeStyle({
      school_name: 'Greenfield School',
      light_tokens: {
        '--color-primary': '4 120 87',
        '--color-primary-hover': '6 95 70',
      },
    })

    expect(style['--color-primary']).toBe('4 120 87')
    expect(style['--weave-blue']).toBe('rgb(var(--color-primary))')
    expect(style['--tenant-accent']).toBe('rgb(var(--color-primary))')
  })

  it('ignores unsupported or malformed frontend token values', () => {
    const branding = normalizeBranding({
      light_tokens: {
        '--color-primary': 'url(javascript:bad)',
        '--evil': '1 2 3',
      },
    })

    expect(branding.light_tokens['--color-primary']).toBe(DEFAULT_LIGHT_TOKENS['--color-primary'])
    expect(branding.light_tokens['--evil']).toBeUndefined()
  })

  it('fills missing theme surfaces with cool neutrals while retaining custom school colors', () => {
    const style = buildBrandingThemeStyle({
      light_tokens: {
        '--color-primary': '132 24 145',
        '--color-surface': '250 247 252',
      },
    })

    expect(style['--color-background']).toBe('248 250 252')
    expect(style['--color-surface-muted']).toBe('248 250 252')
    expect(style['--color-primary']).toBe('132 24 145')
    expect(style['--color-surface']).toBe('250 247 252')
  })
})
