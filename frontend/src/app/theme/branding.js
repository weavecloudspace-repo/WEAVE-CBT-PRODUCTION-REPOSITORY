export const DEFAULT_LIGHT_TOKENS = Object.freeze({
  '--color-primary': '29 78 216',
  '--color-primary-hover': '30 64 175',
  '--color-primary-soft': '239 246 255',
  '--color-primary-subtle': '248 250 252',
  '--color-primary-deep': '30 58 138',
  '--color-on-primary': '255 255 255',
  '--color-accent': '79 70 229',
  '--color-accent-hover': '67 56 202',
  '--color-accent-soft': '238 242 255',
  '--color-on-accent': '255 255 255',
  '--color-background': '248 250 252',
  '--color-surface': '255 255 255',
  '--color-surface-raised': '255 255 255',
  '--color-surface-muted': '248 250 252',
  '--color-surface-subtle': '241 245 249',
  '--color-border': '226 232 240',
  '--color-border-strong': '203 213 225',
  '--color-border-subtle': '241 245 249',
  '--color-text': '15 23 42',
  '--color-text-soft': '51 65 85',
  '--color-text-muted': '100 116 139',
  '--color-text-faint': '148 163 184',
  '--color-text-inverse': '255 255 255',
  '--color-sidebar-background': '255 255 255',
  '--color-sidebar-text': '15 23 42',
  '--color-sidebar-active': '29 78 216',
  '--color-sidebar-active-text': '255 255 255',
  '--color-sidebar-border': '226 232 240',
  '--color-header-background': '255 255 255',
  '--color-header-text': '15 23 42',
  '--color-header-text-muted': '100 116 139',
  '--color-header-surface': '248 250 252',
  '--color-header-surface-hover': '241 245 249',
  '--color-header-border': '226 232 240',
  '--color-focus-ring': '29 78 216',
})

const SUPPORTED_TOKEN_KEYS = new Set(Object.keys(DEFAULT_LIGHT_TOKENS))

function normalizeChannels(value, fallback) {
  const parts = String(value || '').trim().split(/\s+/)
  if (parts.length !== 3) return fallback
  const channels = parts.map(Number)
  if (channels.some((channel) => !Number.isInteger(channel) || channel < 0 || channel > 255)) return fallback
  return channels.join(' ')
}

export function createDefaultBranding() {
  return {
    tenant_id: null,
    school_name: 'Weave CBT',
    logo_revision: null,
    is_enabled: false,
    is_default_theme: true,
    theme_version: 0,
    token_schema_version: 4,
    light_tokens: { ...DEFAULT_LIGHT_TOKENS },
    is_synced: false,
  }
}

export function normalizeBranding(payload) {
  const fallback = createDefaultBranding()
  if (!payload || typeof payload !== 'object') return fallback

  const lightTokens = { ...DEFAULT_LIGHT_TOKENS }
  Object.entries(payload.light_tokens || {}).forEach(([key, value]) => {
    if (!SUPPORTED_TOKEN_KEYS.has(key)) return
    lightTokens[key] = normalizeChannels(value, lightTokens[key])
  })

  return {
    ...fallback,
    ...payload,
    school_name: payload.school_name || fallback.school_name,
    light_tokens: lightTokens,
  }
}

function applyOfficialMark(style) {
  style['--weave-thread-one-start'] = '#60a5fa'
  style['--weave-thread-one-mid'] = '#1d4ed8'
  style['--weave-thread-one-end'] = '#1e3a8a'
  style['--weave-thread-one-halo'] = '#bfdbfe'
  style['--weave-thread-two-start'] = '#fde68a'
  style['--weave-thread-two-mid'] = '#f59e0b'
  style['--weave-thread-two-end'] = '#b45309'
  style['--weave-thread-two-halo'] = '#fef3c7'
}

function applyTenantMark(style, tokens) {
  style['--weave-thread-one-start'] = `rgb(${tokens['--color-primary-soft']})`
  style['--weave-thread-one-mid'] = `rgb(${tokens['--color-primary']})`
  style['--weave-thread-one-end'] = `rgb(${tokens['--color-primary-deep']})`
  style['--weave-thread-one-halo'] = `rgb(${tokens['--color-primary-soft']})`
  style['--weave-thread-two-start'] = `rgb(${tokens['--color-accent-soft']})`
  style['--weave-thread-two-mid'] = `rgb(${tokens['--color-accent']})`
  style['--weave-thread-two-end'] = `rgb(${tokens['--color-accent-hover']})`
  style['--weave-thread-two-halo'] = `rgb(${tokens['--color-accent-soft']})`
}

export function buildBrandingThemeStyle(branding) {
  const normalized = normalizeBranding(branding)
  const style = { ...normalized.light_tokens }

  style['--bg'] = 'rgb(var(--color-background))'
  style['--surface'] = 'rgb(var(--color-surface))'
  style['--surface-soft'] = 'rgb(var(--color-surface-muted))'
  style['--ink'] = 'rgb(var(--color-text))'
  style['--muted'] = 'rgb(var(--color-text-muted))'
  style['--line'] = 'rgb(var(--color-border))'
  style['--weave-navy'] = 'rgb(var(--color-text))'
  style['--weave-blue'] = 'rgb(var(--color-primary))'
  style['--weave-blue-dark'] = 'rgb(var(--color-primary-hover))'
  style['--tenant-accent'] = 'rgb(var(--color-primary))'
  style['--tenant-accent-soft'] = 'rgb(var(--color-primary-soft))'
  style['--tenant-accent-ink'] = 'rgb(var(--color-primary-deep))'

  if (normalized.is_enabled && !normalized.is_default_theme) {
    applyTenantMark(style, normalized.light_tokens)
  } else {
    applyOfficialMark(style)
  }

  return style
}
