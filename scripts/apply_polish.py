from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = ROOT / "render_templates"
STYLE = "<link rel=\"stylesheet\" href=\"{{ url_for('static', filename='css/foundstore-refinement.css') }}\">"

for path in TEMPLATES.glob("*.html"):
    text = path.read_text(encoding="utf-8")
    if "foundstore-refinement.css" not in text and "</head>" in text:
        text = text.replace("</head>", f"    {STYLE}\n</head>", 1)
    path.write_text(text, encoding="utf-8")

path = TEMPLATES / "index.html"
text = path.read_text(encoding="utf-8")
text = text.replace('<label class="search" aria-label="Buscar"><span aria-hidden="true"><svg viewBox="0 0 24 24"><circle cx="11" cy="11" r="6.5"/><path d="m16 16 4.5 4.5"/></svg></span><input id="search" type="search" autocomplete="off"></label>', '<label class="search" aria-label="Buscar usuarios y paquetes"><span aria-hidden="true"><svg viewBox="0 0 24 24"><circle cx="11" cy="11" r="6.5"/><path d="m16 16 4.5 4.5"/></svg></span><input id="search" type="search" autocomplete="off" placeholder="@usuario o paquete" spellcheck="false"></label>')
text = text.replace("const term=search.value.trim().toLowerCase(),fresh=", "const rawTerm=search.value.trim().toLowerCase(),term=rawTerm.startsWith('@')?rawTerm.slice(1):rawTerm,fresh=")
text = text.replace("&&`${p.name} ${p.description||''} ${(p.tags||[]).join(' ')}`.toLowerCase().includes(term)", "&&(rawTerm.startsWith('@')?String(p.author||'').toLowerCase().includes(term):`${p.name} ${p.description||''} ${(p.tags||[]).join(' ')}`.toLowerCase().includes(term))")
text = text.replace("String(p.name||'')", "String(p.name||'')")
path.write_text(text, encoding="utf-8")
