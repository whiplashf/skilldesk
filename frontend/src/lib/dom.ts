const TYPING_TAGS = new Set(['INPUT', 'TEXTAREA', 'SELECT']);

/** True when the event target would swallow plain character keys. */
export function isTypingTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) {
    return false;
  }
  return TYPING_TAGS.has(target.tagName) || target.isContentEditable;
}
