import { withQuery } from '../api/client';

function relativeTarget(value: string, file: string): { path: string; anchor: string } | null {
  if (/^(?:[a-z][a-z0-9+.\-]*:|\/\/)/i.test(value)) return null;
  const parts = value.startsWith('/') ? [] : file.split('/').slice(0, -1);
  const url = value.split(/[?#]/, 1)[0] ?? '';
  for (const segment of (url || file.split('/').pop() || 'SKILL.md').split('/')) {
    const name = decodeURIComponent(segment);
    if (!name || name === '.') continue;
    if (name === '..') {
      if (!parts.length) throw new Error('outside skill');
      parts.pop();
    } else parts.push(name);
  }
  return { path: parts.join('/'), anchor: value.includes('#') ? decodeURIComponent(value.slice(value.indexOf('#') + 1)) : '' };
}

export function resolveAssetSources(html: string, key: string, file = 'SKILL.md'): string {
  const template = document.createElement('template');
  template.innerHTML = html;
  const base = '/api/skill/' + encodeURIComponent(key);
  for (const node of template.content.querySelectorAll('a[href],img[src]')) {
    const image = node.tagName === 'IMG';
    const attr = image ? 'src' : 'href';
    const value = node.getAttribute(attr) || '';
    try {
      const target = relativeTarget(value, file);
      if (!target) {
        if (image) {
          const button = document.createElement('button');
          button.type = 'button';
          const alt = node.getAttribute('alt') || '';
          button.textContent = '加载外部图片' + (alt ? ' · ' + alt : '');
          if (/^https?:\/\//i.test(value)) {
            button.dataset.remoteImage = value;
            button.dataset.alt = alt;
            node.replaceWith(button);
          } else node.replaceWith(alt);
        }
        continue;
      }
      node.setAttribute(attr, withQuery(base + (image ? '/asset' : '/file'), { rel: target.path }));
      if (!image) {
        node.removeAttribute('target');
        node.setAttribute('data-file', target.path);
        if (target.anchor) node.setAttribute('data-anchor', target.anchor);
      }
    } catch { node.removeAttribute(attr); }
  }
  return template.innerHTML;
}
