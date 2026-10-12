import { Icon } from '../../../shared/icons/Icon'
import { TeacherQuestionsPage } from '../../teacher/TeacherQuestionsPage'
import '../admin-workspace-overrides.css'

export function AdminQuestionsPage({ state, dispatch, adminData, gateway, onNavigate }) {
  return (
    <div className="admin-questions-page">
      <div className="teacher-page-heading admin-questions-heading">
        <div>
          <div className="teacher-page-title-line">
            <span className="teacher-page-title-icon"><Icon name="fileText" size={27} /></span>
            <h1>Questions</h1>
          </div>
          <p>Browse, create, edit and manage every question available across the school question banks.</p>
        </div>
        <button className="teacher-primary-action" type="button" disabled={adminData.banks.filter((bank) => bank.status === 'Ready').length === 0} onClick={() => {
          const firstActiveBank = adminData.banks.find((bank) => bank.status === 'Ready')
          onNavigate('create-question', { selectedBankId: firstActiveBank?.id || null, selectedQuestionId: null, editingQuestion: null })
        }}>
          <Icon name="plus" size={18} /> Add Question
        </button>
      </div>
      <div className="admin-questions-page__shared">
        <TeacherQuestionsPage state={state} dispatch={dispatch} teacherData={adminData} gateway={gateway} />
      </div>
    </div>
  )
}
