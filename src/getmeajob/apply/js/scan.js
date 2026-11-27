// Run in the page by getmeajob.apply (guards.py). Reads the page only.
() => {
  const visible = (el) => {
    if (!el || !el.isConnected) return false;
    const s = getComputedStyle(el);
    if (s.display === 'none' || s.visibility === 'hidden' || Number(s.opacity) === 0) return false;
    const r = el.getBoundingClientRect();
    return r.width > 0 && r.height > 0;
  };
  const text = (el) => (el ? (el.innerText || el.textContent || '') : '').replace(/\s+/g, ' ').trim();
  const frames = Array.from(document.querySelectorAll('iframe')).map((f) => {
    const r = f.getBoundingClientRect();
    return { src: f.src || f.getAttribute('src') || '', title: f.title || '',
      visible: visible(f) && r.width > 30 && r.height > 30, badge: !!f.closest('.grecaptcha-badge') };
  });
  const inputs = Array.from(document.querySelectorAll('input')).filter(visible);
  const password = inputs.some((i) => (i.type || '').toLowerCase() === 'password');
  const otp = inputs.some((i) => (i.autocomplete || '') === 'one-time-code' ||
    /security[-_ ]?code|verification[-_ ]?code|\botp\b|one[-_]?time/i.test((i.id || '') + ' ' + (i.name || '')));
  const errors = [];
  const push = (t) => { t = t.slice(0, 200); if (t && !errors.includes(t)) errors.push(t); };
  const sel = '.helper-text--error, .error-message, .field-error, .application-error, [id$="-error"], ' +
    '[role=alert], [class*="_error"], [class*="error-text"]';
  for (const e of document.querySelectorAll(sel)) {
    if (!visible(e) || e.querySelector('input, textarea, select')) continue;
    const t = text(e);
    if (t && t.length < 300) push(t);
  }
  for (const i of document.querySelectorAll('[aria-invalid=true]')) {
    if (!visible(i)) continue;
    let label = '';
    if (i.id) {
      const l = document.querySelector('label[for="' + CSS.escape(i.id) + '"]');
      if (l) label = text(l).replace(/\*/g, '').trim();
    }
    push('field marked invalid: ' + (label || i.id || i.name || i.tagName.toLowerCase()));
  }
  return { url: location.href, title: document.title || '', body: text(document.body).slice(0, 30000),
    frames, password, otp, errors: errors.slice(0, 12) };
}
