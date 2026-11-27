// Run in the page by getmeajob.apply (inspect.py). Reads the page only.
() => {
  const text = (n) => (n ? (n.innerText || n.textContent || '') : '').replace(/\s+/g, ' ').trim();
  const labelOf = (el) => {
    if (el.id) {
      const l = document.querySelector('label[for="' + CSS.escape(el.id) + '"]');
      if (l) return text(l);
    }
    const by = el.getAttribute('aria-labelledby');
    if (by) return by.split(/\s+/).map((id) => text(document.getElementById(id))).join(' ').trim();
    if (el.getAttribute('aria-label')) return el.getAttribute('aria-label');
    const fs = el.closest('fieldset');
    if (fs && fs.querySelector('legend')) return text(fs.querySelector('legend'));
    const wrap = el.closest('label');
    if (wrap) return text(wrap);
    return el.getAttribute('placeholder') || '';
  };
  const out = [];
  const groups = new Map();
  for (const el of document.querySelectorAll('input, textarea, select')) {
    const tag = el.tagName.toLowerCase();
    let kind = tag === 'input' ? (el.getAttribute('type') || 'text').toLowerCase() : tag;
    if (['hidden', 'submit', 'button', 'reset', 'image'].includes(kind)) continue;
    if (el.classList.contains('select__input')) kind = 'react-select';
    else if (el.getAttribute('role') === 'combobox') kind = 'combobox';
    const label = labelOf(el);
    const required = el.required || el.getAttribute('aria-required') === 'true' || /\*\s*$/.test(label);
    if (kind === 'radio' || kind === 'checkbox') {
      if (el.hidden || getComputedStyle(el).display === 'none') continue;  // e.g. behind Yes/No buttons
      const key = el.name || el.id;
      const own = el.id ? document.querySelector('label[for="' + CSS.escape(el.id) + '"]') : null;
      if (!groups.has(key)) {
        const fs = el.closest('fieldset');
        const legend = fs && fs.querySelector('legend, label:not([for="' + CSS.escape(el.id || '') + '"])');
        const entry = { field: key, kind, label: legend ? text(legend) : '', required, options: [] };
        groups.set(key, entry);
        out.push(entry);
      }
      const g = groups.get(key);
      g.required = g.required || required;
      g.options.push(text(own || el.closest('label')) || el.value);
      continue;
    }
    const options = tag === 'select' ? Array.from(el.options).map(text).filter(Boolean) : [];
    out.push({ field: el.id || el.name || '', kind, label, required, options });
  }
  for (const box of document.querySelectorAll('div, fieldset')) {
    const buttons = Array.from(box.children).filter((c) => c.tagName === 'BUTTON');
    const words = buttons.map((b) => text(b).toLowerCase());
    if (buttons.length === 2 && words.includes('yes') && words.includes('no')) {
      const holder = box.parentElement;
      const l = holder ? holder.querySelector('label') : null;
      out.push({ field: l ? l.getAttribute('for') || '' : '', kind: 'yes-no buttons',
        label: l ? text(l) : '', required: !!(l && /required/i.test(l.className)), options: ['Yes', 'No'] });
    }
  }
  return out;
}
