import { toastBus } from '../shared/ui/useToast'

const DEFAULT_API_BASE_URL = '/api/v1'
const STAFF_TOKEN_KEY = 'weave.staffAccessToken'

const statusLabels = {
  400: 'Invalid request',
  401: 'Session problem',
  403: 'Permission problem',
  404: 'Resource missing',
  409: 'This action is not available right now',
  429: 'Rate limit',
}

export class WeaveApiError extends Error {
  constructor({ status, statusText, detail, payload }) {
    super(detail || statusLabels[status] || statusText || 'Request failed')
    this.name = 'WeaveApiError'
    this.status = status
    this.statusText = statusText
    this.detail = detail
    this.payload = payload
  }

  get userMessage() {
    if (this.detail && !looksLikeInternalError(this.detail)) return this.detail
    if (this.status >= 500) return 'Weave could not complete that request. Try again, then contact support if it continues.'
    return statusLabels[this.status] || this.message
  }
}

export function getApiBaseUrl() {
  return (import.meta.env.VITE_WEAVE_API_BASE_URL || DEFAULT_API_BASE_URL).replace(/\/$/, '')
}

export function getStaffAccessToken() {
  return window.localStorage.getItem(STAFF_TOKEN_KEY)
}

export function setStaffAccessToken(token) {
  if (token) window.localStorage.setItem(STAFF_TOKEN_KEY, token)
}

export function clearStaffAccessToken() {
  window.localStorage.removeItem(STAFF_TOKEN_KEY)
}

function requestHeadersFor({ headers = {}, staffAuth = true } = {}) {
  const requestHeaders = { ...headers }
  const token = getStaffAccessToken()
  if (staffAuth && token) requestHeaders.Authorization = `Bearer ${token}`
  return requestHeaders
}

export async function weaveRequest(path, options = {}) {
  const {
    body,
    headers = {},
    method = 'GET',
    signal,
    staffAuth = true,
    formData = false,
    successMessage,
  } = options

  const requestHeaders = requestHeadersFor({ headers, staffAuth })
  if (body !== undefined && !formData) requestHeaders['Content-Type'] = 'application/json'

  const response = await fetch(`${getApiBaseUrl()}${path}`, {
    method,
    headers: requestHeaders,
    credentials: 'include',
    signal,
    body: body === undefined ? undefined : formData ? body : JSON.stringify(body),
  })

  if (response.status === 204) {
    showSuccessMessage(successMessage, null)
    return null
  }

  const payload = await parsePayload(response)
  if (!response.ok) throwApiError(response, payload)

  showSuccessMessage(successMessage, payload)
  return payload
}

export async function weaveBlobRequest(path, options = {}) {
  const { headers = {}, signal, staffAuth = true } = options
  const response = await fetch(`${getApiBaseUrl()}${path}`, {
    method: 'GET',
    headers: requestHeadersFor({ headers, staffAuth }),
    credentials: 'include',
    signal,
  })

  if (!response.ok) {
    const payload = await parsePayload(response)
    throwApiError(response, payload)
  }

  return response.blob()
}

export function queryString(params) {
  const search = new URLSearchParams()
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== '') search.set(key, value)
  })
  const value = search.toString()
  return value ? `?${value}` : ''
}

function showSuccessMessage(successMessage, payload) {
  if (!successMessage) return
  const message = typeof successMessage === 'function' ? successMessage(payload) : successMessage
  if (message) toastBus.success(message)
}

async function parsePayload(response) {
  const text = await response.text()
  if (!text) return null
  try {
    return JSON.parse(text)
  } catch {
    return { detail: text }
  }
}

function throwApiError(response, payload) {
  throw new WeaveApiError({
    status: response.status,
    statusText: response.statusText,
    detail: extractDetail(payload),
    payload,
  })
}

function extractDetail(payload) {
  if (!payload) return ''
  if (typeof payload.detail === 'string') return payload.detail
  if (Array.isArray(payload.detail)) return 'Some fields need attention.'
  if (
    payload.detail
    && typeof payload.detail === 'object'
    && typeof payload.detail.message === 'string'
  ) return payload.detail.message
  return ''
}

function looksLikeInternalError(message) {
  return /traceback|sqlalchemy|integrityerror|constraint|psycopg|asyncpg/i.test(message)
}
