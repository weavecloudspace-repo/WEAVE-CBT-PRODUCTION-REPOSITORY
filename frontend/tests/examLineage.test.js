import { describe, expect, it, vi } from 'vitest'
import { currentExamRevisions, examRevisionHistory, loadAllExams } from '../src/shared/exams/examLineage'

describe('exam lineage data', () => {
  it('keeps distinct terms and components separate without using titles', () => {
    const root = { id: 'root', termId: 'term', curriculumSubjectId: 'subject', assessmentComponentId: 'ca', title: 'Same', revisionNumber: 1 }
    const next = { ...root, id: 'next', title: 'Renamed', revisionNumber: 2 }
    const other = { ...root, id: 'other', assessmentComponentId: 'final' }
    expect(currentExamRevisions([root, other, next]).map((exam) => exam.id)).toEqual(['next', 'other'])
  })
  it('loads remaining API pages before selecting current revisions', async () => {
    const listExams = vi.fn().mockResolvedValueOnce({ exams: Array.from({ length: 200 }, (_, id) => ({ id })), total: 201 }).mockResolvedValueOnce({ exams: [{ id: 200 }], total: 201 })
    expect((await loadAllExams({ listExams })).exams).toHaveLength(201)
    expect(listExams).toHaveBeenLastCalledWith({ offset: 200, limit: 200 })
  })
})

it('keeps linked historical revisions together after a draft scope change', () => {
  const root = { id: 'root', termId: 'term', curriculumSubjectId: 'subject', assessmentComponentId: 'ca', revisionNumber: 1 }
  const next = { ...root, id: 'next', revisionOfExamId: 'root', assessmentComponentId: 'final', revisionNumber: 2 }
  expect(currentExamRevisions([root, next])).toEqual([next])
  expect(examRevisionHistory([root, next], next)).toEqual([next, root])
})
