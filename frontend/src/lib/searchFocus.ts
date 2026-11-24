/**
 * The search box lives inside the library page, but `/` is a global shortcut.
 * Pages register their focus handler; a request made before mount (route change) is queued.
 */
type FocusHandler = () => void;

let handler: FocusHandler | null = null;
let pending = false;

export function registerSearchFocus(next: FocusHandler): () => void {
  handler = next;
  if (pending) {
    pending = false;
    next();
  }
  return () => {
    if (handler === next) {
      handler = null;
    }
  };
}

/** Returns false when the library page is not mounted yet; the focus is applied on mount. */
export function focusSearch(): boolean {
  if (handler !== null) {
    handler();
    return true;
  }
  pending = true;
  return false;
}
