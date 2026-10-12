import { StudentSuspensionNotice } from '../features/student/StudentSuspensionNotice'
import { StudentCompletedExamPage } from '../features/student/StudentCompletedExamPage'
import { ToastHost } from '../shared/ui/ToastHost'
import { PageScrollbar } from '../shared/ui/PageScrollbar'
import { StudentLoginPage } from '../features/auth/StudentLoginPage'
import { LandingPage } from '../features/landing/LandingPage'
import { StudentWorkspace } from '../features/student/StudentWorkspace'
import { ProductLoadingScreen } from './ProductLoadingScreen'
import { studentGateway } from './studentGateway'
import { buildBrandingThemeStyle, createDefaultBranding } from './theme/branding'
import { useAppController } from './useAppController'

export default function StudentApp() {
  const { state, studentSuspension, dismissStudentSuspension, handleStudentSuspension, dispatch, boot, signInStudent, signOut } = useAppController({
    application: 'student',
    gateway: studentGateway,
  })
  const branding = state.installation.configured ? state.branding : createDefaultBranding()
  const completed = state.studentResolution?.state === 'completed'

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
      {state.view === 'student-unavailable' && (
        <ProductLoadingScreen
          title="CBT server not ready"
          copy="This CBT server has not been configured yet. Ask a school administrator to complete setup from the staff application."
        />
      )}
      {state.view === 'landing' && <LandingPage dispatch={dispatch} audience="student" branding={branding} />}
      {state.view === 'student-login' && (
        <StudentLoginPage
          error={state.authError}
          loading={state.authLoading}
          branding={branding}
          onSubmit={signInStudent}
          onBack={() => dispatch({ type: 'view', view: 'landing' })}
        />
      )}
      {state.view === 'student' && completed && (
        <StudentCompletedExamPage gateway={studentGateway} returnToSignIn={signOut} dispatch={dispatch} isMakeup={state.studentResolution?.isMakeup} />
      )}
      {state.view === 'student' && !completed && (
        <StudentWorkspace serverName={state.installation.status?.server_name} onExamSuspended={handleStudentSuspension}
          branding={branding}
          schoolName={state.installation.status?.tenant_name}
          exam={state.exam}
          resolution={state.studentResolution}
          gateway={studentGateway}
          dispatch={dispatch}
          returnToSignIn={signOut}
        />
      )}
      {!completed && <StudentSuspensionNotice notice={studentSuspension} onDismiss={dismissStudentSuspension} />}
      <PageScrollbar />
      <ToastHost />
    </div>
  )
}
