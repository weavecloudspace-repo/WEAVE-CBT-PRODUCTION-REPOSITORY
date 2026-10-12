import { Icon } from '../../shared/icons/Icon'
import { StatusBadge } from '../../shared/ui'

export function BankIcon({ name }) {
  const iconName = name === 'flask' ? 'flask' : name === 'math' ? 'math' : name === 'weave' ? 'weaveIcon' : 'book'
  return <span className={`bank-icon bank-icon--${name}`}><Icon name={iconName} size={34} /></span>
}

export function QuestionRows({ questions, onPreview }) {
  if (!questions.length) {
    return (
      <section className="teacher-bank-question-list teacher-bank-question-list--empty" aria-label="Questions in this bank">
        <strong>No questions in this bank yet</strong>
        <p>Questions created from the Questions section will appear here.</p>
      </section>
    )
  }

  return (
    <section className="teacher-bank-question-list" aria-label="Questions in this bank">
      <div className="teacher-bank-question-list__header" aria-hidden="true">
        <span>Question</span>
        <span>Type</span>
        <span>Status</span>
        <span>Version</span>
      </div>
      {questions.map((question, index) => (
        <article className="teacher-bank-question-row" key={question.id}>
          {onPreview && <button className="teacher-question-row__preview" type="button" aria-label={`Preview question: ${question.prompt}`} onClick={() => onPreview(question)} />}
          <span className="teacher-bank-question-row__number">{index + 1}</span>
          <div className="teacher-bank-question-row__prompt">
            <strong>{question.prompt}</strong>
            {question.image && <small>Includes an image</small>}
          </div>
          <span className="teacher-bank-question-row__type">{question.type}</span>
          <StatusBadge tone={question.status === 'Ready' ? 'success' : 'warning'}>{question.status}</StatusBadge>
          <span className="teacher-bank-question-row__version">{question.updated}</span>
        </article>
      ))}
    </section>
  )
}
