from pathlib import Path

root = Path(__file__).resolve().parents[1]
head = '''  <link rel="manifest" href="/manifest.webmanifest?v=pwa2">
  <link rel="icon" href="/favicon.ico?v=pwa2" type="image/png">
  <link rel="apple-touch-icon" sizes="192x192" href="/static/pwa/icon-192.png?v=pwa2">
  <meta name="theme-color" content="#39e6a0">
'''
for path in sorted((root / 'render_templates').glob('*.html')):
    text = path.read_text(encoding='utf-8')
    if 'manifest.webmanifest?v=pwa2' not in text:
        text = text.replace('  <meta charset=', head + '  <meta charset=', 1)
        path.write_text(text, encoding='utf-8')
        print(path.name)
