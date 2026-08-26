from pathlib import Path
import re

root = Path(__file__).resolve().parents[1]
path = root / 'render_templates' / 'landing.html'
text = path.read_text(encoding='utf-8')
replacement = '''<figure class="landing-visual" aria-label="Vista previa de la tienda Foundstore">
  <div class="store-preview">
    <div class="store-preview-top"><span class="store-preview-dot"></span><span>FOUNDSTORE / DESTACADOS</span><span class="store-preview-status">LIVE</span></div>
    <div class="store-preview-heading"><span>Selección de la semana</span><strong>Paquetes que encajan</strong></div>
    <div class="store-preview-card"><div class="store-preview-icon">F</div><div><strong>PackageMaker</strong><span>por @JesusQuijada</span></div><b>→</b></div>
    <div class="store-preview-card"><div class="store-preview-icon alt">D</div><div><strong>DaneDesk Tools</strong><span>destacado del creador</span></div><b>→</b></div>
    <div class="store-preview-foot"><span>17 idiomas</span><span>•</span><span>aprobación local</span></div>
  </div>
</figure>'''
new_text, count = re.subn(r'<figure class="install-demo".*?</figure>', replacement, text, count=1, flags=re.S)
if count != 1:
    raise SystemExit('No se encontró el bloque install-demo')
path.write_text(new_text, encoding='utf-8')
print('landing visual rebuilt')
