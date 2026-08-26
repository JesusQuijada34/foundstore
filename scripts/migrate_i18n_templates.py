from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "render_templates"

for path in ROOT.glob("*.html"):
    text = path.read_text(encoding="utf-8")
    text = text.replace('{% from "_foundstore_brand.html" import foundstore_brand %}', '{% from "_foundstore_brand.html" import foundstore_brand with context %}')
    text = text.replace('<html lang="es">', '<html lang="{{ current_locale }}">')
    text = text.replace('<html lang="en">', '<html lang="{{ current_locale }}">')
    text = text.replace('<html lang="{{ locale }}">', '<html lang="{{ current_locale }}">')
    text = text.replace('<html lang="{{ current_locale }}" data-locale="es">', '<html lang="{{ current_locale }}">')
    text = text.replace('<html lang="es" data-country="{{ visitor_country }}">', '<html lang="{{ current_locale }}" data-country="{{ visitor_country }}">')
    path.write_text(text, encoding="utf-8")

# Existing pages with a local language control now expose the complete catalog.
for name in ("account.html", "settings.html"):
    path = ROOT / name
    text = path.read_text(encoding="utf-8")
    text = text.replace('<select class="select" id="language"><option value="auto">Automático</option><option value="es">Español</option><option value="en">English</option><option value="pt">Português</option></select>', '<select class="select" id="language" data-language-selector><option value="auto">Automático</option>{% for code, name in available_locales.items() %}<option value="{{ code }}"{% if code == current_locale %} selected{% endif %}>{{ name }}</option>{% endfor %}</select>')
    path.write_text(text, encoding="utf-8")

for name in ("index.html", "package.html"):
    path = ROOT / name
    text = path.read_text(encoding="utf-8")
    old = '<select class="language" id="language" aria-label="Idioma"><option value="es">Español</option><option value="en">English</option><option value="pt">Português</option><option value="ru">Русский</option></select>'
    old2 = '<select class="lang" id="language"><option value="es">ES</option><option value="en">EN</option><option value="pt">PT</option><option value="ru">RU</option></select>'
    replacement = '<select class="language" id="language" data-language-selector aria-label="{{ t(\'Language\') }}">{% for code, name in available_locales.items() %}<option value="{{ code }}"{% if code == current_locale %} selected{% endif %}>{{ name }}</option>{% endfor %}</select>'
    replacement2 = '<select class="lang" id="language" data-language-selector aria-label="{{ t(\'Choose language\') }}">{% for code, name in available_locales.items() %}<option value="{{ code }}"{% if code == current_locale %} selected{% endif %}>{{ code }}</option>{% endfor %}</select>'
    text = text.replace(old, replacement).replace(old2, replacement2)
    path.write_text(text, encoding="utf-8")
