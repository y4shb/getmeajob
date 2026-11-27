// Run in the page by getmeajob.apply (base.py). Reads the page only.
() => {
  const visible = (n) => {
    const s = getComputedStyle(n);
    const r = n.getBoundingClientRect();
    return s.display !== 'none' && s.visibility !== 'hidden' && r.width > 0 && r.height > 0;
  };
  const out = [];
  const seen = new Set();
  for (const el of document.querySelectorAll('input, textarea, select')) {
    const req = el.required || el.getAttribute('aria-required') === 'true';
    const type = (el.type || '').toLowerCase();
    if (!req || ['hidden', 'submit', 'button', 'checkbox'].includes(type)) continue;
    const key = el.id || el.name;
    if (!key || seen.has(key)) continue;
    seen.add(key);
    if (type === 'file') { if (!el.files || !el.files.length) out.push(key); continue; }
    if (!visible(el) && !el.classList.contains('select__input')) continue;
    if (type === 'radio') {
      if (!document.querySelector('input[type=radio][name="' + CSS.escape(el.name) + '"]:checked')) out.push(el.name);
      continue;
    }
    if (el.classList.contains('select__input')) {
      let chosen = '';
      for (let node = el, i = 0; node && i < 5 && !chosen; i += 1) {
        node = node.parentElement;
        const sv = node ? node.querySelector('.select__single-value, .select__multi-value__label') : null;
        if (sv && !sv.hidden) chosen = sv.textContent.trim();
      }
      if (!chosen) out.push(key);
      continue;
    }
    if (!String(el.value || '').trim()) out.push(key);
  }
  return out;
}
