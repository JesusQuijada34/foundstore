import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import app

locales = ['es','en','fr','de','pt','it','nl','ca','ja','ko','zh-CN','ru','ar','hi','tr','pl','uk']
with app.test_client() as client:
    for locale in locales:
        response = client.get(f'/?lang={locale}')
        html = response.get_data(as_text=True)
        assert response.status_code == 200
        assert f'<html lang="{locale}">' in html
        assert "foundstore-v2.css') }}?v=pwa5" not in html
        assert 'foundstore-v2.css?v=pwa5' in html
        assert "data-language-selector" in html
        assert "value=\"auto\"" in html
        print(locale, response.status_code, len(html))
print('i18n mobile validation OK')
