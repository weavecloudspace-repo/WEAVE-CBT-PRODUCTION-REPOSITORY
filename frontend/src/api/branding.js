import { getApiBaseUrl, weaveRequest } from './client'

export function getBranding({ signal } = {}) {
  return weaveRequest('/branding', { signal, staffAuth: false })
}

export function getLocalBrandLogoSrc(branding) {
  if (!branding?.logo_revision || !branding?.logo_path || !branding?.is_enabled) return null
  return `${getApiBaseUrl()}/branding/logo?v=${encodeURIComponent(branding.logo_revision)}`
}
