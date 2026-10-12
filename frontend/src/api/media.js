import { weaveRequest } from './client'

export function uploadQuestionImage(file) {
  const body = new FormData()
  body.set('file', file)
  return weaveRequest('/media/question-images', { method: 'POST', body, formData: true })
}
