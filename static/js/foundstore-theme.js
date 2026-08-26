(() => {
  const key = 'foundstore-theme';
  const root = document.documentElement;
  const button = document.querySelector('[data-theme-toggle]');
  const icon = document.querySelector('[data-theme-icon]');
  const label = document.querySelector('[data-theme-label]');
  const meta = document.querySelector('meta[name="theme-color"]');
  const saved = localStorage.getItem(key);
  const system = matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
  const apply = theme => {
    root.dataset.theme = theme;
    root.style.colorScheme = theme;
    if (meta) meta.content = theme === 'dark' ? '#07131a' : '#f8fbf8';
    if (button) button.setAttribute('aria-pressed', String(theme === 'dark'));
    if (icon) icon.textContent = theme === 'dark' ? '☀' : '☾';
    if (label) label.textContent = theme === 'dark' ? 'Cambiar a modo claro' : 'Cambiar a modo oscuro';
  };
  apply(saved === 'dark' || saved === 'light' ? saved : system);
  button?.addEventListener('click', () => {
    const next = root.dataset.theme === 'dark' ? 'light' : 'dark';
    localStorage.setItem(key, next);
    apply(next);
  });
})();
