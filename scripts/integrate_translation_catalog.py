import json
from pathlib import Path

root = Path(__file__).resolve().parents[1]
data = json.loads((root / 'static/i18n/catalog.json').read_text(encoding='utf-8'))
js = 'window.FoundstoreTranslations = ' + json.dumps(data, ensure_ascii=False, separators=(',', ':')) + ';\n'
(root / 'static/js/foundstore-translations.js').write_text(js, encoding='utf-8')

path = root / 'render_templates/index.html'
text = path.read_text(encoding='utf-8')
if 'foundstore-translations.js' not in text:
    text = text.replace('<script>\n      const owner=', '<script src="{{ url_for(\'static\', filename=\'js/foundstore-translations.js\') }}"></script>\n    <script>\n      const owner=', 1)
text = text.replace('if(!words[locale])locale=\'es\'', "if(!window.FoundstoreTranslations?.[locale]&&!words[locale])locale='es'")
text = text.replace("const t=k=>words[locale][k]||words.es[k]", "const t=k=>(window.FoundstoreTranslations?.[locale]||words[locale]||words.es)[k]||(window.FoundstoreTranslations?.es||words.es)[k]")
path.write_text(text, encoding='utf-8')
