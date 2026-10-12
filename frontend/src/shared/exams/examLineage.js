// Titles are presentation; the academic assessment scope owns the lineage.
export function examLineageKey(exam) {
  return JSON.stringify([exam.termId, exam.curriculumSubjectId, exam.assessmentComponentId])
}

// Parent links preserve history even if an older draft changed its assessment scope.
function lineageKeys(exams) {
  const byId = new Map(exams.map((exam) => [exam.id, exam]))
  return new Map(exams.map((exam) => {
    let root = exam
    const visited = new Set([root.id])
    while (byId.has(root.revisionOfExamId) && !visited.has(root.revisionOfExamId)) {
      root = byId.get(root.revisionOfExamId)
      visited.add(root.id)
    }
    return [exam.id, examLineageKey(root)]
  }))
}

export function currentExamRevisions(exams) {
  const keys = lineageKeys(exams)
  const current = new Map()
  for (const exam of exams) {
    const key = keys.get(exam.id)
    if (!current.has(key) || Number(exam.revisionNumber || 1) > Number(current.get(key).revisionNumber || 1)) current.set(key, exam)
  }
  return [...current.values()]
}

export function examRevisionHistory(exams, exam) {
  const keys = lineageKeys(exams)
  return exams.filter((item) => keys.get(item.id) === keys.get(exam.id))
    .sort((a, b) => Number(b.revisionNumber || 1) - Number(a.revisionNumber || 1))
}

export async function loadAllExams(examsApi, params = {}) {
  const rows = []
  for (;;) {
    const payload = await examsApi.listExams({ ...params, offset: rows.length, limit: 200 })
    const batch = Array.isArray(payload) ? payload : payload?.exams || []
    rows.push(...batch)
    if (!batch.length || Array.isArray(payload) || rows.length >= (payload?.total ?? rows.length)) return { exams: rows }
  }
}
