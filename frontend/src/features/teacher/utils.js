export function statusTone(status) {
  if (status === 'Ready' || status === 'Sealed') return 'success'
  if (status === 'Draft' || status === 'Changes Requested') return 'warning'
  return 'neutral'
}
