from __future__ import annotations

import json
from pathlib import Path
from openai import OpenAI

LOCALES = ["es", "en", "fr", "de", "pt", "it", "nl", "ca", "ja", "ko", "zh-CN", "ru", "ar", "hi", "tr", "pl", "uk"]
KEYS = ["browse", "checking", "title", "subtitle", "loading", "all", "featured", "categories", "signin", "signed", "noDevices", "linkHint", "devices", "open", "empty", "failed", "Language", "Choose language", "Back", "Download", "Author", "Platform", "Version", "Category", "Information", "Privacy", "Error"]
SOURCE = {
    "browse": "Explorar", "checking": "Comprobando sesión…", "title": "Aplicaciones para tu DaneDesk", "subtitle": "Explora software Fluthin. Abre una ficha para conocer la aplicación y solicita su instalación en un DaneDesk ya vinculado a tu cuenta.", "loading": "Cargando catálogo…", "all": "Todo", "featured": "Destacado", "categories": "Categorías", "signin": "Iniciar sesión con GitHub", "signed": "Sesión iniciada", "noDevices": "Tu cuenta está lista, pero aún no tiene DaneDesk vinculados.", "linkHint": "La licencia pertenece al dispositivo, no a tu cuenta web. Inicia el vínculo desde Foundstore Agent en el DaneDesk para que aparezca aquí.", "devices": "DaneDesk disponibles", "open": "Ver ficha", "empty": "No hay aplicaciones que coincidan.", "failed": "No se pudo cargar el catálogo.", "Language": "Idioma", "Choose language": "Elegir idioma", "Back": "Volver", "Download": "Descargar", "Author": "Autor", "Platform": "Plataforma", "Version": "Versión", "Category": "Categoría", "Information": "Información", "Privacy": "Privacidad", "Error": "Error",
}

prompt = """Translate the following Foundstore UI glossary from Spanish into every requested locale. Return JSON only with one object per locale and exactly the same keys. Preserve proper nouns and product names exactly: Foundstore, Fluthin, DaneDesk, Danenone, Knosthalij, GitHub, Foundstore Agent. Preserve ellipses and concise UI tone. Do not translate keys, only values.\n\nLocales: """ + ", ".join(LOCALES) + "\nSource JSON:\n" + json.dumps(SOURCE, ensure_ascii=False)

schema = {"type": "object", "properties": {locale: {"type": "object", "properties": {key: {"type": "string"} for key in KEYS}, "required": KEYS, "additionalProperties": False} for locale in LOCALES}, "required": LOCALES, "additionalProperties": False}
client = OpenAI()
response = client.chat.completions.create(model="gpt-5-mini", messages=[{"role": "system", "content": "You are a meticulous product UI translator."}, {"role": "user", "content": prompt}], response_format={"type": "json_schema", "json_schema": {"name": "foundstore_translations", "strict": True, "schema": schema}}, max_completion_tokens=12000)
data = json.loads(response.choices[0].message.content)
for locale in LOCALES:
    if set(data[locale]) != set(KEYS):
        raise SystemExit(f"Invalid key set for {locale}")
output = Path(__file__).resolve().parents[1] / "static" / "i18n" / "catalog.json"
output.parent.mkdir(parents=True, exist_ok=True)
output.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(output)
