/** Relative `src` values in rendered SKILL.md are relative to the skill directory, not the app URL. */
const ABSOLUTE_SCHEME = /^[a-zA-Z][a-zA-Z0-9+.-]*:/;

export function resolveAssetSources(html: string, identityKey: string): string {
  if (!html.includes('<img')) {
    return html;
  }

  const document_ = new DOMParser().parseFromString(`<div id="rendered">${html}</div>`, 'text/html');
  const root = document_.getElementById('rendered');
  if (root === null) {
    return html;
  }

  let rewritten = false;
  for (const image of root.querySelectorAll('img')) {
    const src = image.getAttribute('src');
    if (src === null || src === '' || src.startsWith('/') || src.startsWith('#') || ABSOLUTE_SCHEME.test(src)) {
      continue;
    }
    const rel = src.replace(/^\.\//, '');
    image.setAttribute(
      'src',
      `/api/skill/${encodeURIComponent(identityKey)}/asset?rel=${encodeURIComponent(rel)}`,
    );
    rewritten = true;
  }

  return rewritten ? root.innerHTML : html;
}
