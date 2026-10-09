import { loadAllExams } from '../../shared/exams/examLineage'
import { useCallback, useEffect, useState } from 'react'

const emptyAdminData = {
  banks: [],
  questions: [],
  exams: [],
  subjects: [],
  assignments: [],
  assessmentSchemes: [],
  assessmentComponents: [],
  session: null,
  term: null,
}

export function useAdminData(gateway) {
  const [data, setData] = useState(emptyAdminData)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [warning, setWarning] = useState('')

  const refresh = useCallback(async ({ silent = false } = {}) => {
    if (!silent) setLoading(true)
    setError('')
    setWarning('')
    try {
      const loaded = await loadAdminData(gateway)
      setData(loaded.data)
      setWarning(loaded.warning)
    } catch (requestError) {
      setError(requestError.userMessage || 'Weave could not load the administrator workspace.')
      if (!silent) setData(emptyAdminData)
    } finally {
      if (!silent) setLoading(false)
    }
  }, [gateway])

  const refreshExams = useCallback(async ({ silent = true } = {}) => {
    if (!silent) setLoading(true)
    try {
      const examPayload = await loadAllExams(gateway.exams)
      const examRows = Array.isArray(examPayload) ? examPayload : examPayload?.exams || []
      setData((current) => {
        const subjectByCurriculum = new Map(current.subjects.map((subject) => [subject.id, subject]))
        const componentById = new Map(current.assessmentComponents.map((component) => [component.id, component]))
        return {
          ...current,
          exams: examRows.map((exam) => normalizeExam(exam, subjectByCurriculum, componentById)),
        }
      })
      setError('')
    } catch (requestError) {
      setError(requestError.userMessage || 'Weave could not refresh examination state.')
    } finally {
      if (!silent) setLoading(false)
    }
  }, [gateway])

  useEffect(() => {
    let cancelled = false
    loadAdminData(gateway)
      .then((loaded) => {
        if (cancelled) return
        setData(loaded.data)
        setWarning(loaded.warning)
        setError('')
      })
      .catch((requestError) => {
        if (cancelled) return
        setError(requestError.userMessage || 'Weave could not load the administrator workspace.')
        setData(emptyAdminData)
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => { cancelled = true }
  }, [gateway])

  return { ...data, loading, error, warning, refresh, refreshExams }
}

async function loadAdminData(gateway) {
  const warnings = []
  const optional = async (request, fallback) => {
    if (typeof request !== 'function') return fallback
    try {
      return (await request()) ?? fallback
    } catch (requestError) {
      warnings.push(requestError.userMessage || requestError.message || 'Some administrator data could not be loaded.')
      return fallback
    }
  }

  const [
    bankRows,
    sessionRow,
    termRow,
    subjectRows,
    assignmentRows,
    examPayload,
    schemeRows,
    questionRows,
  ] = await Promise.all([
    gateway.questions.listAdminQuestionBanks({ include_archived: true }),
    optional(gateway.academics?.getCurrentAcademicSession, null),
    optional(gateway.academics?.getCurrentAcademicTerm, null),
    optional(gateway.academics?.listAuthorableCurriculumSubjects, []),
    optional(gateway.academics?.listEffectiveTeacherAssignments, []),
    optional(() => loadAllExams(gateway.exams), { exams: [] }),
    optional(() => gateway.academics?.listAssessmentSchemes?.({ active_only: true }), []),
    optional(() => gateway.questions?.listManageableQuestions?.({ include_archived: true }), []),
  ])

  const bankById = new Map(bankRows.map((bank) => [bank.id, bank]))
  const questions = questionRows
    .map((question) => {
      const bank = bankById.get(question.bank_id)
      return bank ? normalizeQuestion(question, bank) : null
    })
    .filter(Boolean)

  const componentGroups = await Promise.all(
    schemeRows.map((scheme) => optional(
      () => gateway.academics?.listAssessmentComponents?.(scheme.id, { active_only: true }),
      [],
    )),
  )

  const subjects = subjectRows.map(normalizeSubject)
  const assignments = assignmentRows.map(normalizeAssignment)
  const assessmentSchemes = schemeRows.map((scheme) => ({ id: scheme.id, name: scheme.name, status: scheme.status }))
  const assessmentComponents = componentGroups.flat().map(normalizeAssessmentComponent)
  const subjectByCurriculum = new Map(subjects.map((subject) => [subject.id, subject]))
  const componentById = new Map(assessmentComponents.map((component) => [component.id, component]))
  const examRows = Array.isArray(examPayload) ? examPayload : examPayload?.exams || []

  return {
    data: {
      banks: bankRows.map((bank) => normalizeBank(bank, questions, subjectByCurriculum)),
      questions,
      exams: examRows.map((exam) => normalizeExam(exam, subjectByCurriculum, componentById)),
      subjects,
      assignments,
      assessmentSchemes,
      assessmentComponents,
      session: sessionRow ? normalizeSession(sessionRow) : null,
      term: termRow ? normalizeTerm(termRow) : null,
    },
    warning: warnings[0] || '',
  }
}

function normalizeBank(bank, questions, subjectByCurriculum) {
  const bankQuestions = questions.filter((question) => question.bankId === bank.id)
  const subject = subjectByCurriculum.get(bank.curriculum_subject_id)
  return {
    id: bank.id,
    curriculumSubjectId: bank.curriculum_subject_id,
    academicLevelId: subject?.academicLevelId || null,
    academicLevelName: subject?.academicLevelName || '',
    subjectName: subject?.name || 'Subject',
    subjectCode: subject?.code || '',
    name: bank.name,
    description: bank.description,
    status: bank.is_active ? 'Ready' : 'Archived',
    count: bankQuestions.length,
    activeQuestionCount: bankQuestions.filter((question) => question.status === 'Ready').length,
    canDelete: bank.can_delete === true,
    createdByActorId: bank.created_by_actor_id,
  }
}

function normalizeQuestion(question, bank) {
  return {
    id: question.id,
    bankId: question.bank_id,
    prompt: question.prompt,
    instruction: question.instruction,
    type: question.question_type === 'multiple_choice' ? 'Multiple choice' : 'Single choice',
    image: Boolean(question.image_asset_id),
    imageAssetId: question.image_asset_id,
    status: question.is_active ? 'Ready' : 'Archived',
    updated: `v${question.version}`,
    version: question.version,
    options: question.options,
    bankName: bank.name,
    canDelete: question.can_delete === true,
    createdByActorId: question.created_by_actor_id,
    lastEditedByActorId: question.last_edited_by_actor_id,
  }
}

function normalizeSubject(subject) {
  return {
    id: subject.id,
    curriculumId: subject.curriculum_id,
    academicLevelId: subject.academic_level_id,
    academicLevelName: subject.academic_level_name,
    academicLevelCategory: subject.academic_level_category,
    academicLevelPosition: Number(subject.academic_level_position ?? 0),
    subjectId: subject.subject_id,
    name: subject.subject_name,
    code: subject.subject_code,
    isElective: subject.is_elective,
    isActive: subject.is_active,
  }
}

function normalizeAssignment(assignment) {
  return {
    id: assignment.id,
    curriculumSubjectId: assignment.curriculum_subject_id,
    subjectId: assignment.subject_id,
    subjectName: assignment.subject_name,
    subjectCode: assignment.subject_code,
    classId: assignment.class_id,
    className: assignment.class_name,
    effectiveFrom: assignment.effective_from,
    effectiveTo: assignment.effective_to,
  }
}

function normalizeAssessmentComponent(component) {
  return {
    id: component.id,
    schemeId: component.assessment_scheme_id,
    name: component.name,
    code: component.code,
    maximumScore: Number(component.maximum_score),
    position: component.position,
    isActive: component.is_active,
  }
}

function normalizeSession(session) {
  return { id: session.id, name: session.name, status: session.status, isCurrent: session.is_current }
}

function normalizeTerm(term) {
  return { id: term.id, sessionId: term.academic_session_id, name: term.name, status: term.status, isCurrent: term.is_current }
}

function normalizeExam(exam, subjectByCurriculum, componentById) {
  const status = String(exam.status || 'draft').toLowerCase()
  const rosterStatus = String(exam.roster_status || 'not_prepared').toLowerCase()
  const subject = subjectByCurriculum.get(exam.curriculum_subject_id)
  const component = componentById.get(exam.assessment_component_id)
  return {
    id: exam.id,
    sessionId: exam.session_id,
    termId: exam.term_id,
    title: exam.title,
    instructions: exam.instructions || '',
    folderColor: exam.folder_color || null,
    academicLevelId: subject?.academicLevelId || null,
    academicLevelName: subject?.academicLevelName || '',
    subjectName: subject?.name || 'Subject',
    subjectCode: subject?.code || '',
    curriculumSubjectId: exam.curriculum_subject_id,
    assessmentSchemeId: exam.assessment_scheme_id,
    assessmentComponentId: exam.assessment_component_id,
    assessmentName: component?.name || 'Assessment',
    questionBankId: exam.question_bank_id,
    questionCount: exam.question_count,
    selectionMode: exam.question_selection_mode,
    durationMinutes: exam.duration_minutes,
    shuffleQuestions: exam.shuffle_questions,
    shuffleOptions: exam.shuffle_options,
    status,
    statusLabel: status.replaceAll('_', ' ').replace(/\b\w/g, (letter) => letter.toUpperCase()),
    scheduledStartAt: exam.scheduled_start_at,
    latestNormalStartAt: exam.latest_normal_start_at,
    rosterStatus,
    rosterVersion: Number(exam.roster_version || 0),
    rosterCandidateCount: Number(exam.roster_candidate_count || 0),
    rosterPreparedAt: exam.roster_prepared_at || null,
    rosterError: exam.roster_error || '',
    authoringVersion: exam.authoring_version,
    revisionNumber: exam.revision_number,
    revisionOfExamId: exam.revision_of_exam_id,
    createdByActorId: exam.created_by_actor_id,
    leadTeacherId: exam.lead_teacher_id,
    leadAssignedAt: exam.lead_assigned_at,
    submittedAt: exam.submitted_at || null,
    sealedAt: exam.sealed_at || null,
    activatedAt: exam.activated_at || null,
    componentMaximumScore: exam.component_maximum_score,
    closedAt: exam.closed_at || null,
    cancelledAt: exam.cancelled_at || null,
    createdAt: exam.created_at,
    updatedAt: exam.updated_at,
  }
}
