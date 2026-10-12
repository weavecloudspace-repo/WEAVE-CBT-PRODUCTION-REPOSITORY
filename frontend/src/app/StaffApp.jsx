import { ToastHost } from '../shared/ui/ToastHost'
import { PageScrollbar } from '../shared/ui/PageScrollbar'
import { useEffect } from 'react'
import { AdminWorkspace } from '../features/admin/AdminWorkspace'
import { StaffLoginPage } from '../features/auth/StaffLoginPage'
import { LandingPage } from '../features/landing/LandingPage'
import { SetupFlow } from '../features/setup/SetupFlow'
import { isSetupView } from '../features/setup/setupViews'
import { InitialSyncPage } from '../features/sync/InitialSyncPage'
import { TeacherWorkspace } from '../features/teacher/TeacherWorkspace'
import { ProductLoadingScreen } from './ProductLoadingScreen'
import { staffGateway } from './staffGateway'
import { buildBrandingThemeStyle, createDefaultBranding } from './theme/branding'
import { useAppController } from './useAppController'

export default function StaffApp() {
  const { state, dispatch, boot, pair, signInStaff, signOut } = useAppController({
    application: 'staff',
    gateway: staffGateway,
  })
  const branding = state.installation.configured ? state.branding : createDefaultBranding()
  const currentRole = state.session?.role || state.session?.type
  const themeStyle = buildBrandingThemeStyle(branding)

  /*
   * Staff confirmation/editor dialogs are rendered through React portals under
   * document.body. CSS custom properties normally inherit from .weave-app, so
   * those portal children would otherwise lose the tenant theme entirely.
   * Mirror the active branding tokens onto the document root while StaffApp is
   * mounted so every portal surface resolves the same school colours as the
   * dashboard that opened it.
   */
  useEffect(() => {
    const root = document.documentElement
    const previous = new Map()

    Object.entries(themeStyle).forEach(([property, value]) => {
      if (!property.startsWith('--')) return
      previous.set(property, root.style.getPropertyValue(property))
      root.style.setProperty(property, String(value))
    })

    return () => {
      previous.forEach((value, property) => {
        if (value) root.style.setProperty(property, value)
        else root.style.removeProperty(property)
      })
    }
  }, [themeStyle])

  return (
    <div className="weave-app" style={themeStyle}>
      {state.view === 'boot' && (
        <ProductLoadingScreen
          title="Starting Weave"
          copy="Checking the local CBT server and installation state."
          error={state.bootError}
          onRetry={() => boot()}
        />
      )}
      {isSetupView(state.view) && (
        <SetupFlow
          view={state.view}
          error={state.authError}
          installation={state.installation}
          dispatch={dispatch}
          onPair={pair}
        />
      )}
      {state.view === 'landing' && <LandingPage dispatch={dispatch} audience="staff" branding={branding} />}
      {state.view === 'staff-login' && (
        <StaffLoginPage
          error={state.authError}
          loading={state.authLoading}
          branding={branding}
          onSubmit={signInStaff}
          onBack={() => dispatch({ type: 'view', view: 'landing' })}
        />
      )}
      {state.view === 'sync-check' && (
        <ProductLoadingScreen
          title="Checking server readiness"
          copy="Reading the local synchronization status."
        />
      )}
      {state.view === 'initial-sync' && (
        <InitialSyncPage
          error={state.syncError}
          status={state.syncStatus}
          branding={branding}
          dispatch={dispatch}
        />
      )}
      {state.view === 'staff' && currentRole === 'teacher' && (
        <TeacherWorkspace
          state={state}
          dispatch={dispatch}
          signOut={signOut}
          gateway={staffGateway}
        />
      )}
      {state.view === 'staff' && currentRole === 'admin' && (
        <AdminWorkspace
          state={state}
          dispatch={dispatch}
          signOut={signOut}
          gateway={staffGateway}
        />
      )}
      <PageScrollbar />
      <ToastHost />
    </div>
  )
}
