from pathlib import Path

root = Path(__file__).resolve().parents[1]
link = '<link rel="stylesheet" href="{{ url_for(\'static\', filename=\'css/foundstore-v2.css\') }}">'
for path in sorted((root / 'render_templates').glob('*.html')):
    text = path.read_text(encoding='utf-8')
    for legacy in ('foundstore-public-upgrade.css', 'foundstore-motion.css', 'foundstore-refinement.css'):
        import re
        text = re.sub(r'\s*<link[^>]*' + re.escape(legacy) + r'[^>]*>', '', text)
    if 'css/foundstore-v2.css' in text:
        path.write_text(text, encoding='utf-8')
        print(path.name)
        continue
    marker = '</head>'
    if marker in text:
        text = text.replace(marker, f'    {link}\n  {marker}', 1)
        path.write_text(text, encoding='utf-8')
        print(path.name)
