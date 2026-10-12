import { useEffect, useState } from 'react'
import { weaveGateway } from '../../app/gateway'

export function useInitialSyncStatus(dispatch) {
  const [readyAnimation, setReadyAnimation] = useState(false)
  const [retrying, setRetrying] = useState(false)

  useEffect(() => {
    let active = true
    let timer
    const controller = new AbortController()

    const check = async () => {
      try {
        const status = await weaveGateway.sync.getSyncStatus({ signal: controller.signal })
        if (!active) return
        if (status.bootstrap_completed_at) {
          setReadyAnimation(true)
          weaveGateway.branding.getBranding()
            .then((branding) => { if (active) dispatch({ type: 'brandingSuccess', branding }) })
            .catch(() => null)
          timer = window.setTimeout(() => { if (active) dispatch({ type: 'syncStatus', status }) }, 700)
          return
        }
        dispatch({ type: 'syncStatus', status })
      } catch (error) {
        if (active && error.name !== 'AbortError') {
          dispatch({ type: 'syncFailure', message: error.userMessage || 'Could not check synchronization status.' })
        }
      }
      if (active) timer = window.setTimeout(check, 2000)
    }

    timer = window.setTimeout(check, 2000)
    return () => { active = false; controller.abort(); window.clearTimeout(timer) }
  }, [dispatch])

  const retry = async () => {
    if (retrying) return
    setRetrying(true)
    try {
      const status = await weaveGateway.sync.reconcileSync()
      dispatch({ type: 'syncStatus', status })
    } catch (error) {
      dispatch({ type: 'syncFailure', message: error.userMessage || 'Retry failed. Please try again.' })
    } finally {
      setRetrying(false)
    }
  }

  return { readyAnimation, retrying, retry }
}
