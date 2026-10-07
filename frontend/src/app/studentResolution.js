export function toStudentResolution(session) {
  return {
    state: session.availability,
    statusMessage: session.status_message,
    exam: session.exam_id ? {
      id: session.exam_id, title: session.exam_title,
      subjectName: session.subject_name, durationMinutes: session.duration_minutes,
      scheduledStartAt: session.scheduled_start_at, activatedAt: session.activated_at,
    } : null,
    candidate: { id: session.candidate_id || null, name: session.display_name, studentId: session.student_id },
    isMakeup: session.is_makeup,
    hasUnfinishedAttempt: session.has_unfinished_attempt === true,
  }
}
