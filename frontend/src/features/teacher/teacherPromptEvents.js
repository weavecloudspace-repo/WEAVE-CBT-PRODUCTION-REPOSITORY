export function handlePromptKeyDown(event, disabled = false) {
  if (event.key !== 'Enter' || event.shiftKey || event.nativeEvent?.isComposing) return
  event.preventDefault()
  if (!disabled) event.currentTarget.form?.requestSubmit()
}
