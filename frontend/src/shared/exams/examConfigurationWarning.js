export function buildDestructiveQuestionConfigurationWarning({ selections = [], changingToRandom = false, changingBank = false }) {
  const questionCount = selections.length
  const contributorCount = new Set(
    selections
      .map((selection) => selection.added_by_actor_id)
      .filter(Boolean)
      .map(String),
  ).size
  const questionText = `${questionCount} manually selected question${questionCount === 1 ? '' : 's'}`
  const contributorText = contributorCount
    ? ` from ${contributorCount} contributor${contributorCount === 1 ? '' : 's'}`
    : ''

  if (changingToRandom) {
    return [
      'Switch to Random Selection?',
      '',
      `${questionText}${contributorText} will be removed from this draft.`,
      '',
      'The questions themselves will remain in the question bank, but their selection for this examination cannot be restored automatically.',
      '',
      'Continue?',
    ].join('\n')
  }

  if (changingBank) {
    return [
      'Change Question Bank?',
      '',
      `${questionText}${contributorText} will be removed from this draft because they belong to the current question bank.`,
      '',
      'The questions themselves will remain in the question bank, but their selection for this examination cannot be restored automatically.',
      '',
      'Continue?',
    ].join('\n')
  }

  return ''
}
