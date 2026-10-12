import { StudentSuspensionNotice } from '../features/student/StudentSuspensionNotice'
import { AdminWorkspace } from '../features/admin/AdminWorkspace'
import { StaffLoginPage } from '../features/auth/StaffLoginPage'
import { StudentLoginPage } from '../features/auth/StudentLoginPage'
import { LandingPage } from '../features/landing/LandingPage'
import { SetupFlow } from '../features/setup/SetupFlow'
import { isSetupView } from '../features/setup/setupViews'
import { StudentWorkspace } from '../features/student/StudentWorkspace'
import { InitialSyncPage } from '../features/sync/InitialSyncPage'
import { TeacherWorkspace } from '../features/teacher/TeacherWorkspace'
import { ToastHost } from '../shared/ui/ToastHost'
import { ProductLoadingScreen } from './ProductLoadingScreen'
import { buildBrandingThemeStyle, createDefaultBranding } from './theme/branding'
import { weaveGateway } from './gateway'
import { useAppController } from './useAppController'

export default function App() {
  const { state, studentSuspension, dismissStudentSuspension, handleStudentSuspension, dispatch, boot, pair, signInStaff, signInStudent, signOut } = useAppController({ gateway: weaveGateway })
  const branding = state.installation.configured ? state.branding : createDefaultBranding()
  const currentRole = state.session?.role || state.session?.type

  return (
    <div className="weave-app" style={buildBrandingThemeStyle(branding)}>
      {state.view === 'boot' && (
        <ProductLoadingScreen
          title="Starting Weave"
          copy="Checking the local CBT server and installation state."
          error={state.bootError}
          onRetry={() => boot()}
        />
      )}
      {isSetupView(state.view) && <SetupFlow view={state.view} error={state.authError} installation={state.installation} dispatch={dispatch} onPair={pair} />}
      {state.view === 'landing' && <LandingPage dispatch={dispatch} branding={branding} />}
      {state.view === 'staff-login' && <StaffLoginPage error={state.authError} loading={state.authLoading} branding={branding} onSubmit={signInStaff} onBack={() => dispatch({ type: 'view', view: 'landing' })} />}
      {state.view === 'student-login' && <StudentLoginPage error={state.authError} loading={state.authLoading} branding={branding} onSubmit={signInStudent} onBack={() => dispatch({ type: 'view', view: 'landing' })} />}
      {state.view === 'sync-check' && <ProductLoadingScreen title="Checking server readiness" copy="Reading the local synchronization status." />}
      {state.view === 'initial-sync' && <InitialSyncPage error={state.syncError} status={state.syncStatus} branding={branding} dispatch={dispatch} />}
      {state.view === 'student' && <StudentWorkspace serverName={state.installation.status?.server_name} onExamSuspended={handleStudentSuspension} branding={branding} schoolName={state.installation.status?.tenant_name} exam={state.exam} resolution={state.studentResolution} gateway={weaveGateway} dispatch={dispatch} returnToSignIn={signOut} />}
      {state.view === 'staff' && currentRole === 'teacher' && <TeacherWorkspace state={state} dispatch={dispatch} signOut={signOut} gateway={weaveGateway} />}
      {state.view === 'staff' && currentRole === 'admin' && <AdminWorkspace state={state} dispatch={dispatch} signOut={signOut} gateway={weaveGateway} />}
      <StudentSuspensionNotice notice={studentSuspension} onDismiss={dismissStudentSuspension} />
      <ToastHost />
    </div>
  )
}
