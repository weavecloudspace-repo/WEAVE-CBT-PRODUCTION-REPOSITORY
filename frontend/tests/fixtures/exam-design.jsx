/* eslint-disable react-refresh/only-export-components */
// Browser-only design fixture. Never imported by either production entrypoint.
import { useState } from 'react'
import { createRoot } from 'react-dom/client'
import { AdminWorkspace } from '../../src/features/admin/AdminWorkspace'
import '../../src/styles/global.css'
import '../../src/app/theme/branding.css'
import '../../src/styles/product-shell.css'
import '../../src/styles/dashboard-polish.css'
import '../../src/styles/dashboard-controls.css'

const statuses = ['draft', 'submitted', 'active', 'suspended', 'submitted', 'closed', 'draft', 'sealed', 'closing', 'cancelling', 'cancelled', 'active']
const titles = ['English CA1', 'JSS2 Maths CA2', 'Basic Science', 'Biology Exam', 'Civic Education CA1', 'Chemistry Exam', 'Physics CA2', 'Further Maths', 'Economics CA1', 'Computer Studies', 'Literature in English: extended assessment title to check truncation', 'Geography CA2']
const rows = titles.map((title, index) => ({
  id: `exam-${index}`, title, status: statuses[index], curriculum_subject_id: 'subject-1', assessment_scheme_id: 'scheme-1', assessment_component_id: 'component-1',
  question_bank_id: 'bank-1', question_count: 20, question_selection_mode: 'random', duration_minutes: 60, authoring_version: 3, revision_number: 1,
  session_id: 'session-1', term_id: 'term-1', lead_teacher_id: 'teacher-1', roster_status: 'ready', roster_candidate_count: 24,
  created_at: '2026-09-12T09:00:00Z', updated_at: '2026-09-18T09:00:00Z', scheduled_start_at: '2026-09-25T09:00:00Z', latest_normal_start_at: '2026-09-25T11:00:00Z',
}))
const gateway = {
  questions: {
    listAdminQuestionBanks: async () => [{ id: 'bank-1', curriculum_subject_id: 'subject-1', name: 'Computer Studies Questions', is_active: true }],
    listManageableQuestions: async () => Array.from({ length: 46 }, (_, i) => ({ id: `question-${i}`, bank_id: 'bank-1', prompt: `Design fixture question ${i + 1}`, is_active: true, question_type: 'single_choice', options: [] })),
  },
  academics: {
    getCurrentAcademicSession: async () => ({ id: 'session-1', name: '2026/2027' }),
    getCurrentAcademicTerm: async () => ({ id: 'term-1', name: 'First Term' }),
    listAuthorableCurriculumSubjects: async () => [{ id: 'subject-1', subject_name: 'Computer Studies' }],
    listAssessmentSchemes: async () => [{ id: 'scheme-1', name: 'CA2', status: 'active' }],
    listAssessmentComponents: async () => [{ id: 'component-1', assessment_scheme_id: 'scheme-1', name: 'Term Exam', maximum_score: 60 }],
  },
  exams: {
    listExams: async () => ({ exams: rows }),
    listLeadCandidates: async () => [{ id: 'teacher-1', first_name: 'Sarah', last_name: 'Johnson' }],
    createExam: async () => { throw new Error('Visual fixture: no records are saved.') },
  },
}
function ExamDesignFixture() {
  const [state, setState] = useState({
    staff: { section: 'exams', selectedExamId: null },
    session: { actor: { id: 'admin-1', role: 'admin', display_name: 'School administrator' } },
    branding: { school_name: 'Weave College' },
  })
  return <div className="weave-app"><AdminWorkspace state={state} dispatch={(action) => setState((current) => ({ ...current, staff: { ...current.staff, ...action.patch } }))} gateway={gateway} signOut={() => {}} /></div>
}
createRoot(document.getElementById('root')).render(<ExamDesignFixture />)
