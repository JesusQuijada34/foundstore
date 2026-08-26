from pathlib import Path

root = Path(__file__).resolve().parents[1]
for path in sorted((root / 'render_templates').glob('*.html')):
    text = path.read_text(encoding='utf-8')
    old = "css/foundstore-v2.css"
    new = "css/foundstore-v2.css?v=1f9870e"
    if old in text and new not in text:
        path.write_text(text.replace(old, new), encoding='utf-8')
        print(path.name)
