import { RiLoader4Line } from '@remixicon/react'

export function TeacherGenerationStatus({ title, detail }) {
  return <div className="teacher-generation-status" role="status">
    <RiLoader4Line className="teacher-generation-status__indicator" size={20} aria-hidden="true" />
    <div><p>{title}</p>{detail && <small>{detail}</small>}</div>
  </div>
}
