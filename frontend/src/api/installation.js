import { weaveRequest } from './client'

export function getInstallationStatus({ signal } = {}) {
  return weaveRequest('/installation/status', { signal, staffAuth: false })
}

export function pairInstallation({ pairingCode, serverName }) {
  return weaveRequest('/installation/pair', {
    method: 'POST',
    staffAuth: false,
    body: { pairing_code: pairingCode, server_name: serverName },
  })
}
