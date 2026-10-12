// Effective assignments are scoped to the signed-in teacher by the API.
// Creator provenance is not proof of current lead ownership.
export function canManageExam(exam, actor, assignments = []) {
  if (exam.status !== 'draft') return false
  if (actor?.role === 'admin') return true
  return actor?.role === 'teacher' && Boolean(exam.leadTeacherId) && assignments.some(
    (assignment) => assignment.teacherMembershipId === exam.leadTeacherId &&
      assignment.curriculumSubjectId === exam.curriculumSubjectId,
  )
}

export const examStatuses = ['all', 'draft', 'submitted', 'sealed', 'active', 'suspended', 'closing', 'closed', 'cancelling', 'cancelled']
