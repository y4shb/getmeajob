// Run in the page by getmeajob.apply (menus.py). Reads the page only.
(el) => {
  for (let node = el, i = 0; node && i < 5; i += 1) {
    node = node.parentElement;
    const sv = node ? node.querySelector('.select__single-value, .select__multi-value__label') : null;
    if (sv && !sv.hidden && sv.textContent.trim()) return sv.textContent.trim();
  }
  return el.value || '';
}
