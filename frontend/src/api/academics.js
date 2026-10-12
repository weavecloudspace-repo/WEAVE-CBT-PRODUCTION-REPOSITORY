import { queryString, weaveRequest } from './client'

export const getCurrentAcademicSession = () => weaveRequest('/academics/session/current')
export const getCurrentAcademicTerm = () => weaveRequest('/academics/term/current')
export const listAuthorableCurriculumSubjects = () => weaveRequest('/academics/curriculum-subjects/authorable')
export const listEffectiveTeacherAssignments = () => weaveRequest('/academics/teacher-assignments/effective')

export function listEligibleClasses(curriculumSubjectId, academicTermId, options = {}) {
  return weaveRequest(
    `/academics/curriculum-subjects/${curriculumSubjectId}/eligible-classes${queryString({ academic_term_id: academicTermId })}`,
    options,
  )
}

export function listAssessmentSchemes(params = {}, options = {}) {
  return weaveRequest(`/academics/assessment-schemes${queryString(params)}`, options)
}

export function listAssessmentComponents(assessmentSchemeId, params = {}, options = {}) {
  return weaveRequest(`/academics/assessment-schemes/${assessmentSchemeId}/components${queryString(params)}`, options)
}
