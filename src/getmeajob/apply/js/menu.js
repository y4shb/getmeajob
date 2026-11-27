// Run in the page by getmeajob.apply (menus.py). Reads the page only.
(el, pick) => {
  const visible = (n) => {
    if (!n || !n.isConnected || n.hidden) return false;
    const s = getComputedStyle(n);
    if (s.display === 'none' || s.visibility === 'hidden') return false;
    const r = n.getBoundingClientRect();
    return r.width > 0 && r.height > 0;
  };
  const text = (n) => (n ? (n.innerText || n.textContent || '') : '').replace(/\s+/g, ' ').trim();
  let menu = null;
  const own = el.getAttribute('aria-controls');
  if (own && visible(document.getElementById(own))) menu = document.getElementById(own);
  for (let node = el, i = 0; !menu && node && i < 8; i += 1) {
    node = node.parentElement;
    const m = node ? node.querySelector('.select__menu') : null;
    if (m && visible(m)) menu = m;
  }
  if (!menu) {
    const open = Array.from(document.querySelectorAll('.select__menu, [role=listbox]')).filter(visible);
    if (open.length === 1) menu = open[0];
  }
  if (!menu) return { open: false, options: [], notice: '', marked: false };
  const opts = Array.from(menu.querySelectorAll('.select__option, [role=option]')).filter(visible);
  if (pick !== null) {
    document.querySelectorAll('[data-getmeajob-pick]').forEach((n) => n.removeAttribute('data-getmeajob-pick'));
    const hit = opts.find((o) => text(o) === pick);
    if (hit) hit.setAttribute('data-getmeajob-pick', '1');
    return { open: true, options: [], notice: '', marked: !!hit };
  }
  const notice = text(menu.querySelector('.select__menu-notice, [class*="notice"], [class*="loading"]'));
  return { open: true, options: opts.map(text), notice, marked: false };
}
