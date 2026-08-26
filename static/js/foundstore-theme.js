(() => {
  const root = document.documentElement;
  const meta = document.querySelector('meta[name="theme-color"]');
  const media = window.matchMedia('(prefers-color-scheme: dark)');
  const apply = () => {
    const theme = media.matches ? 'dark' : 'light';
    root.dataset.theme = theme;
    root.style.colorScheme = theme;
    if (meta) meta.content = media.matches ? '#07131a' : '#f8fbf8';
  };
  apply();
  media.addEventListener?.('change', apply);
  media.addListener?.(apply);
})();
