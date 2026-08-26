from pathlib import Path
from PIL import Image, ImageDraw

root = Path(__file__).resolve().parents[1]
source = root / 'static' / 'logo_foundstore_transparent.png'
out = root / 'static' / 'pwa'
out.mkdir(parents=True, exist_ok=True)
logo = Image.open(source).convert('RGBA')

for size in (192, 512):
    canvas = Image.new('RGBA', (size, size), '#07131a')
    inset = int(size * .14)
    mark = logo.copy()
    mark.thumbnail((size - inset * 2, size - inset * 2), Image.Resampling.LANCZOS)
    canvas.alpha_composite(mark, ((size - mark.width) // 2, (size - mark.height) // 2))
    canvas.convert('RGB').save(out / f'icon-{size}.png', optimize=True)

for name, size, bg in (
    ('splash-light', (1125, 2436), '#f8fbf8'),
    ('splash-dark', (1125, 2436), '#07131a'),
):
    canvas = Image.new('RGBA', size, bg)
    # Use a centered, compact mark with generous safe area for mobile splash screens.
    mark = logo.copy()
    mark.thumbnail((int(size[0] * .34), int(size[0] * .34)), Image.Resampling.LANCZOS)
    canvas.alpha_composite(mark, ((size[0] - mark.width) // 2, int(size[1] * .42)))
    draw = ImageDraw.Draw(canvas)
    draw.text((size[0] // 2, int(size[1] * .58)), 'FOUNDSTORE', fill='#19b978' if 'light' in name else '#39e6a0', anchor='mm')
    canvas.convert('RGB').save(out / f'{name}.png', optimize=True)
print('PWA assets created')
