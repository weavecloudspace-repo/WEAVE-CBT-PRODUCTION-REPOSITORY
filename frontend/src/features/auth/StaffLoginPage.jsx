import { useState } from 'react'
import { LoginField, LoginShell } from './LoginShell'

export function StaffLoginPage({ error, loading, branding, onSubmit, onBack }) {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')

  return (
    <LoginShell
      kind="staff"
      branding={branding}
      title="Staff Login"
      subtitle="Access your CBT staff account"
      error={error}
      loading={loading}
      onBack={onBack}
      onSubmit={() => onSubmit({ email: email.trim(), password })}
    >
      <LoginField
        label="Email Address"
        name="staff_email"
        type="email"
        autoComplete="off"
        value={email}
        onChange={setEmail}
        placeholder="you@school.edu.ng"
      />
      <LoginField
        label="Password"
        name="staff_password"
        type="password"
        autoComplete="new-password"
        value={password}
        onChange={setPassword}
        placeholder="Enter your password"
      />
    </LoginShell>
  )
}
