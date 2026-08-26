from pathlib import Path

root = Path(__file__).resolve().parents[1]
for path in sorted((root / 'render_templates').glob('*.html')):
    text = path.read_text(encoding='utf-8')
    text = text.replace("{{ url_for('static', filename='css/foundstore-v2.css') }}?v=1f9870e) }}", "{{ url_for('static', filename='css/foundstore-v2.css') }}?v=1f9870e")
    text = text.replace("{{ url_for('static', filename='css/foundstore-v2.css?v=1f9870e') }}", "{{ url_for('static', filename='css/foundstore-v2.css') }}?v=1f9870e")
    path.write_text(text, encoding='utf-8')
    print(path.name)
