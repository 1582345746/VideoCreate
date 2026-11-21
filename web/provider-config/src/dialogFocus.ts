// Keep sequential keyboard navigation inside the active native modal. Escape,
// browser shortcuts and the existing dirty-form confirmation retain their behavior.
export function containDialogFocus(event: KeyboardEvent) {
  if (event.key !== 'Tab' || event.defaultPrevented || event.altKey || event.ctrlKey || event.metaKey) return
  const dialog = event.currentTarget as HTMLDialogElement
  if (!dialog.open) return
  function visibleThroughDetails(el: HTMLElement) {
    // Chrome may return nonempty rectangles for descendants of closed details.
    // Only the direct summary (and its children) participates in focus order;
    // a nested summary still has to pass every closed ancestor.
    for (let parent = el.parentElement; parent && parent !== dialog; parent = parent.parentElement) {
      if (parent instanceof HTMLDetailsElement && !parent.open && !parent.querySelector(':scope > summary')?.contains(el)) return false
    }
    return true
  }
  const controls = Array.from(dialog.querySelectorAll<HTMLElement>(
    'a[href],button,input,select,textarea,summary,[tabindex]'
  )).filter(el => el.tabIndex >= 0 && !el.matches(':disabled') && !el.closest('[inert]') &&
    visibleThroughDetails(el) && el.getClientRects().length > 0 && getComputedStyle(el).visibility !== 'hidden')
  const first = controls[0], last = controls[controls.length - 1]
  if (!first) { event.preventDefault(); dialog.focus(); return }
  const current = document.activeElement
  if (event.shiftKey && (current === first || current === dialog || !dialog.contains(current))) {
    event.preventDefault(); last?.focus()
  } else if (!event.shiftKey && (current === last || current === dialog || !dialog.contains(current))) {
    event.preventDefault(); first.focus()
  }
}
