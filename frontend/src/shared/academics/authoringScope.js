export function buildAcademicLevels(subjects = []) {
  const levels = new Map()

  for (const subject of subjects) {
    if (!subject?.academicLevelId) continue
    const current = levels.get(subject.academicLevelId)
    const candidate = {
      id: subject.academicLevelId,
      name: subject.academicLevelName || 'Academic level',
      category: subject.academicLevelCategory || '',
      position: Number(subject.academicLevelPosition ?? 0),
    }

    if (!current || candidate.position < current.position) levels.set(candidate.id, candidate)
  }

  return [...levels.values()].sort((left, right) => {
    if (left.position !== right.position) return left.position - right.position
    return left.name.localeCompare(right.name)
  })
}

export function listSubjectsForLevel(subjects = [], academicLevelId) {
  if (!academicLevelId) return []
  return subjects.filter((subject) => subject.academicLevelId === academicLevelId)
}

export function findSubjectScope(subjects = [], curriculumSubjectId) {
  if (!curriculumSubjectId) return null
  return subjects.find((subject) => subject.id === curriculumSubjectId) || null
}

export function listBanksForSubject(banks = [], curriculumSubjectId) {
  if (!curriculumSubjectId) return []
  return banks.filter((bank) => bank.curriculumSubjectId === curriculumSubjectId)
}

export function humanizeAcademicCategory(value) {
  if (!value) return ''
  return String(value).replaceAll('_', ' ').replace(/\b\w/g, (letter) => letter.toUpperCase())
}
