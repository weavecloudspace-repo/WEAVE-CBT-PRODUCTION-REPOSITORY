import { weaveRequest } from './client'

export async function loginStudent({ admissionNumber, password }) {
  const session = await weaveRequest('/student/auth/login', {
    method: 'POST',
    staffAuth: false,
    body: { admission_number: admissionNumber.trim().toUpperCase(), password },
  })
  return { type: 'student', name: session.display_name, ...session }
}

export async function getStudentStatus() {
  const session = await weaveRequest('/student/auth/status', {
    method: 'GET',
    staffAuth: false,
  })
  return { type: 'student', name: session.display_name, ...session }
}

export async function logoutStudent() {
  return weaveRequest('/student/auth/logout', { method: 'POST', staffAuth: false })
}
