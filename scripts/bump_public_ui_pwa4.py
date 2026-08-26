from pathlib import Path

root = Path(__file__).resolve().parents[1]
for path in sorted((root / 'render_templates').glob('*.html')):
    text = path.read_text(encoding='utf-8')
    updated = text.replace("css/foundstore-v2.css') }}?v=pwa3", "css/foundstore-v2.css') }}?v=pwa4")
    if updated != text:
        path.write_text(updated, encoding='utf-8')
        print(path.name)
