import { queryString, weaveRequest } from './client'

export function getMyAIQuota(options = {}) {
  return weaveRequest('/ai/quota', options)
}

export function requestAICredits(credits, options = {}) {
  return weaveRequest('/ai/quota/requests', {
    ...options,
    method: 'POST',
    body: { credits },
  })
}

export function listMyAIQuotaRequests(params = {}, options = {}) {
  return weaveRequest(`/ai/quota/requests${queryString(params)}`, options)
}

export function cancelAIQuotaRequest(requestId, options = {}) {
  return weaveRequest(`/ai/quota/requests/${encodeURIComponent(requestId)}/cancel`, {
    ...options,
    method: 'POST',
  })
}

export function getAIQuotaSummary(options = {}) {
  return weaveRequest('/ai/admin/quota/summary', options)
}

export function listAIActorBalances(options = {}) {
  return weaveRequest('/ai/admin/quota/actors', options)
}

export function listAIQuotaRequests(params = {}, options = {}) {
  return weaveRequest(`/ai/admin/quota/requests${queryString(params)}`, options)
}

export function approveAIQuotaRequest(requestId, payload = {}, options = {}) {
  return weaveRequest(`/ai/admin/quota/requests/${encodeURIComponent(requestId)}/approve`, {
    ...options,
    method: 'POST',
    body: payload,
  })
}

export function rejectAIQuotaRequest(requestId, payload = {}, options = {}) {
  return weaveRequest(`/ai/admin/quota/requests/${encodeURIComponent(requestId)}/reject`, {
    ...options,
    method: 'POST',
    body: payload,
  })
}

export function allocateAICredits(payload, options = {}) {
  return weaveRequest('/ai/admin/quota/allocations', {
    ...options,
    method: 'POST',
    body: payload,
  })
}

export function listAIAllocations(params = {}, options = {}) {
  return weaveRequest(`/ai/admin/quota/allocations${queryString(params)}`, options)
}

export function quoteAICreditPurchase(credits, options = {}) {
  return weaveRequest('/ai/admin/quota/purchases/quote', {
    ...options,
    method: 'POST',
    body: { credits },
  })
}

export function startAICreditPurchase(credits, options = {}) {
  return weaveRequest('/ai/admin/quota/purchases/checkout', {
    ...options,
    method: 'POST',
    body: { credits },
  })
}

export function verifyAICreditPurchase(reference, options = {}) {
  return weaveRequest(
    `/ai/admin/quota/purchases/${encodeURIComponent(reference)}/verify`,
    {
      ...options,
      method: 'POST',
    },
  )
}

export function listAICreditPurchases(params = {}, options = {}) {
  return weaveRequest(`/ai/admin/quota/purchases${queryString(params)}`, options)
}

export function getAICreditPurchase(purchaseId, options = {}) {
  return weaveRequest(
    `/ai/admin/quota/purchases/${encodeURIComponent(purchaseId)}`,
    options,
  )
}
