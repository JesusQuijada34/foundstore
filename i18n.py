"""Internationalization helpers for Foundstore.

The catalog is intentionally dependency-free so the Flask service remains easy to
run on Render. Unknown locales are normalized and safely fall back to Spanish.
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path
from functools import lru_cache
from typing import Any

import requests
from flask import Request

DEFAULT_LOCALE = "es"
COOKIE_NAME = "foundstore_locale"
SUPPORTED_LOCALES = {
    "es": "Español", "en": "English", "fr": "Français", "de": "Deutsch",
    "pt": "Português", "it": "Italiano", "nl": "Nederlands", "ca": "Català",
    "ja": "日本語", "ko": "한국어", "zh-CN": "简体中文", "ru": "Русский",
    "ar": "العربية", "hi": "हिन्दी", "tr": "Türkçe", "pl": "Polski", "uk": "Українська",
}
COUNTRY_TO_LOCALE = {
    "ES":"es","MX":"es","AR":"es","BO":"es","CL":"es","CO":"es","CR":"es","CU":"es","DO":"es","EC":"es","GT":"es","HN":"es","NI":"es","PA":"es","PE":"es","PR":"es","PY":"es","SV":"es","UY":"es","VE":"es",
    "US":"en","GB":"en","IE":"en","CA":"en","AU":"en","NZ":"en","IN":"hi","SG":"en","PH":"en","ZA":"en",
    "FR":"fr","BE":"fr","LU":"fr","MC":"fr","CH":"fr",
    "DE":"de","AT":"de","LI":"de",
    "PT":"pt","BR":"pt","IT":"it","NL":"nl","ID":"en","JP":"ja","KR":"ko","CN":"zh-CN","TW":"zh-CN","HK":"zh-CN",
    "RU":"ru","BY":"ru","KZ":"ru","KG":"ru","TJ":"ru","TM":"ru","UZ":"ru","UA":"uk","TR":"tr","PL":"pl",
    "SA":"ar","AE":"ar","EG":"ar","MA":"ar","DZ":"ar","TN":"ar","JO":"ar","LB":"ar","IQ":"ar","IL":"ar",
}

TRANSLATIONS: dict[str, dict[str, str]] = {
    "es": {
        "Language": "Idioma", "Choose language": "Elegir idioma", "Home": "Inicio", "Packages": "Paquetes", "Developers": "Desarrolladores", "Settings": "Configuración", "Help": "Ayuda", "Sign in": "Iniciar sesión", "Sign out": "Cerrar sesión", "Back": "Volver", "Search": "Buscar", "Download": "Descargar", "Loading…": "Cargando…", "Try again later.": "Vuelve a intentarlo más tarde.", "Not available": "No disponible", "Public catalog": "Catálogo público", "Your profile": "Tu perfil", "Follow": "Seguir", "Following": "Siguiendo", "followers": "seguidores", "following": "seguidos", "packages": "paquetes", "Developer": "Desarrollador", "Author": "Autor", "Platform": "Plataforma", "Version": "Versión", "Category": "Categoría", "Package name": "Nombre del paquete", "Information": "Información", "Privacy": "Privacidad", "Error": "Error",
    },
    "en": {
        "Language": "Language", "Choose language": "Choose language", "Home": "Home", "Packages": "Packages", "Developers": "Developers", "Settings": "Settings", "Help": "Help", "Sign in": "Sign in", "Sign out": "Sign out", "Back": "Back", "Search": "Search", "Download": "Download", "Loading…": "Loading…", "Try again later.": "Try again later.", "Not available": "Not available", "Public catalog": "Public catalog", "Your profile": "Your profile", "Follow": "Follow", "Following": "Following", "followers": "followers", "following": "following", "packages": "packages", "Developer": "Developer", "Author": "Author", "Platform": "Platform", "Version": "Version", "Category": "Category", "Package name": "Package name", "Information": "Information", "Privacy": "Privacy", "Error": "Error",
    },
}

# High-value UI strings are translated explicitly; every other key safely falls
# back to Spanish so a missing translation never breaks rendering.
TRANSLATIONS.update({locale: dict(TRANSLATIONS["en"]) for locale in SUPPORTED_LOCALES if locale not in TRANSLATIONS})
COMMON_TRANSLATIONS = {
    "es": {"Profile":"Perfil","Licenses":"Licencias","Devices":"Dispositivos","Privacy":"Privacidad","Invalid packages":"Paquetes inválidos","Preferences":"Preferencias","Back to catalog":"Volver al catálogo","Account":"Cuenta","Public profile":"Perfil público","Public name":"Nombre público","Bio":"Biografía","Website":"Sitio web HTTPS","Save profile":"Guardar perfil","Save privacy":"Guardar privacidad","Visibility":"Visibilidad","Public":"Público","Private":"Privado","Repositories":"Repositorios","Followers":"Seguidores","Following":"Seguidos","Create license":"Crear licencia","Linked devices":"Dispositivos vinculados","Open panel":"Abrir panel","Browser preferences":"Preferencias del navegador","Reset preferences":"Restablecer preferencias","Package security":"Seguridad del paquete","Static analysis":"Análisis estático","GitHub star":"Estrella GitHub","Account navigation":"Navegación de cuenta","Avatar":"Avatar","Organize your account in separate sections. Sensitive actions still require GitHub session and local confirmation when applicable.":"Organiza tu cuenta en secciones independientes. Las acciones sensibles siguen requiriendo sesión GitHub y confirmación local cuando corresponde."},
    "en": {"Profile":"Profile","Licenses":"Licenses","Devices":"Devices","Privacy":"Privacy","Invalid packages":"Invalid packages","Preferences":"Preferences","Back to catalog":"Back to catalog","Account":"Account","Public profile":"Public profile","Public name":"Public name","Bio":"Bio","Website":"HTTPS website","Save profile":"Save profile","Save privacy":"Save privacy","Visibility":"Visibility","Public":"Public","Private":"Private","Repositories":"Repositories","Followers":"Followers","Following":"Following","Create license":"Create license","Linked devices":"Linked devices","Open panel":"Open panel","Browser preferences":"Browser preferences","Reset preferences":"Reset preferences","Package security":"Package security","Static analysis":"Static analysis","GitHub star":"GitHub star","Account navigation":"Account navigation","Avatar":"Avatar","Organize your account in separate sections. Sensitive actions still require GitHub session and local confirmation when applicable.":"Organize your account in separate sections. Sensitive actions still require a GitHub session and local confirmation when applicable."},
    "fr": {"Profile":"Profil","Licenses":"Licences","Devices":"Appareils","Privacy":"Confidentialité","Invalid packages":"Paquets invalides","Preferences":"Préférences","Back to catalog":"Retour au catalogue","Account":"Compte","Public profile":"Profil public","Public name":"Nom public","Bio":"Biographie","Website":"Site web HTTPS","Save profile":"Enregistrer le profil","Save privacy":"Enregistrer la confidentialité","Visibility":"Visibilité","Public":"Public","Private":"Privé","Repositories":"Dépôts","Followers":"Abonnés","Following":"Abonnements","Create license":"Créer une licence","Linked devices":"Appareils liés","Open panel":"Ouvrir le panneau","Browser preferences":"Préférences du navigateur","Reset preferences":"Réinitialiser les préférences","Package security":"Sécurité du paquet","Static analysis":"Analyse statique","GitHub star":"Étoile GitHub"},
    "de": {"Profile":"Profil","Licenses":"Lizenzen","Devices":"Geräte","Privacy":"Datenschutz","Invalid packages":"Ungültige Pakete","Preferences":"Einstellungen","Back to catalog":"Zurück zum Katalog","Account":"Konto","Public profile":"Öffentliches Profil","Public name":"Öffentlicher Name","Bio":"Biografie","Website":"HTTPS-Website","Save profile":"Profil speichern","Save privacy":"Datenschutz speichern","Visibility":"Sichtbarkeit","Public":"Öffentlich","Private":"Privat","Repositories":"Repositories","Followers":"Follower","Following":"Gefolgt","Create license":"Lizenz erstellen","Linked devices":"Verknüpfte Geräte","Open panel":"Panel öffnen","Browser preferences":"Browsereinstellungen","Reset preferences":"Einstellungen zurücksetzen","Package security":"Paketsicherheit","Static analysis":"Statische Analyse","GitHub star":"GitHub-Stern"},
    "pt": {"Profile":"Perfil","Licenses":"Licenças","Devices":"Dispositivos","Privacy":"Privacidade","Invalid packages":"Pacotes inválidos","Preferences":"Preferências","Back to catalog":"Voltar ao catálogo","Account":"Conta","Public profile":"Perfil público","Public name":"Nome público","Bio":"Biografia","Website":"Site HTTPS","Save profile":"Salvar perfil","Save privacy":"Salvar privacidade","Visibility":"Visibilidade","Public":"Público","Private":"Privado","Repositories":"Repositórios","Followers":"Seguidores","Following":"Seguindo","Create license":"Criar licença","Linked devices":"Dispositivos vinculados","Open panel":"Abrir painel","Browser preferences":"Preferências do navegador","Reset preferences":"Redefinir preferências","Package security":"Segurança do pacote","Static analysis":"Análise estática","GitHub star":"Estrela do GitHub"},
    "it": {"Profile":"Profilo","Licenses":"Licenze","Devices":"Dispositivi","Privacy":"Privacy","Invalid packages":"Pacchetti non validi","Preferences":"Preferenze","Back to catalog":"Torna al catalogo","Account":"Account","Public profile":"Profilo pubblico","Public name":"Nome pubblico","Bio":"Biografia","Website":"Sito HTTPS","Save profile":"Salva profilo","Save privacy":"Salva privacy","Visibility":"Visibilità","Public":"Pubblico","Private":"Privato","Repositories":"Repository","Followers":"Follower","Following":"Seguiti","Create license":"Crea licenza","Linked devices":"Dispositivi collegati","Open panel":"Apri pannello","Browser preferences":"Preferenze del browser","Reset preferences":"Ripristina preferenze","Package security":"Sicurezza del pacchetto","Static analysis":"Analisi statica","GitHub star":"Stella GitHub"},
    "nl": {"Profile":"Profiel","Licenses":"Licenties","Devices":"Apparaten","Privacy":"Privacy","Invalid packages":"Ongeldige pakketten","Preferences":"Voorkeuren","Back to catalog":"Terug naar catalogus","Account":"Account","Public profile":"Openbaar profiel","Public name":"Openbare naam","Bio":"Biografie","Website":"HTTPS-website","Save profile":"Profiel opslaan","Save privacy":"Privacy opslaan","Visibility":"Zichtbaarheid","Public":"Openbaar","Private":"Privé","Repositories":"Repositories","Followers":"Volgers","Following":"Volgend","Create license":"Licentie maken","Linked devices":"Gekoppelde apparaten","Open panel":"Paneel openen","Browser preferences":"Browservoorkeuren","Reset preferences":"Voorkeuren herstellen","Package security":"Pakketbeveiliging","Static analysis":"Statische analyse","GitHub star":"GitHub-ster"},
    "ca": {"Profile":"Perfil","Licenses":"Llicències","Devices":"Dispositius","Privacy":"Privadesa","Invalid packages":"Paquets no vàlids","Preferences":"Preferències","Back to catalog":"Torna al catàleg","Account":"Compte","Public profile":"Perfil públic","Public name":"Nom públic","Bio":"Biografia","Website":"Lloc web HTTPS","Save profile":"Desa el perfil","Save privacy":"Desa la privadesa","Visibility":"Visibilitat","Public":"Públic","Private":"Privat","Repositories":"Repositoris","Followers":"Seguidors","Following":"Seguint","Create license":"Crea una llicència","Linked devices":"Dispositius vinculats","Open panel":"Obre el tauler","Browser preferences":"Preferències del navegador","Reset preferences":"Restableix les preferències","Package security":"Seguretat del paquet","Static analysis":"Anàlisi estàtica","GitHub star":"Estrella de GitHub"},
    "ja": {"Profile":"プロフィール","Licenses":"ライセンス","Devices":"デバイス","Privacy":"プライバシー","Invalid packages":"無効なパッケージ","Preferences":"設定","Back to catalog":"カタログに戻る","Account":"アカウント","Public profile":"公開プロフィール","Public name":"公開名","Bio":"自己紹介","Website":"HTTPSサイト","Save profile":"プロフィールを保存","Save privacy":"プライバシーを保存","Visibility":"公開範囲","Public":"公開","Private":"非公開","Repositories":"リポジトリ","Followers":"フォロワー","Following":"フォロー中","Create license":"ライセンスを作成","Linked devices":"リンク済みデバイス","Open panel":"パネルを開く","Browser preferences":"ブラウザ設定","Reset preferences":"設定をリセット","Package security":"パッケージの安全性","Static analysis":"静的解析","GitHub star":"GitHubスター"},
    "ko": {"Profile":"프로필","Licenses":"라이선스","Devices":"기기","Privacy":"개인정보","Invalid packages":"잘못된 패키지","Preferences":"환경설정","Back to catalog":"카탈로그로 돌아가기","Account":"계정","Public profile":"공개 프로필","Public name":"공개 이름","Bio":"소개","Website":"HTTPS 웹사이트","Save profile":"프로필 저장","Save privacy":"개인정보 저장","Visibility":"공개 범위","Public":"공개","Private":"비공개","Repositories":"저장소","Followers":"팔로워","Following":"팔로잉","Create license":"라이선스 만들기","Linked devices":"연결된 기기","Open panel":"패널 열기","Browser preferences":"브라우저 설정","Reset preferences":"환경설정 초기화","Package security":"패키지 보안","Static analysis":"정적 분석","GitHub star":"GitHub 별"},
    "zh-CN": {"Profile":"个人资料","Licenses":"许可证","Devices":"设备","Privacy":"隐私","Invalid packages":"无效软件包","Preferences":"偏好设置","Back to catalog":"返回目录","Account":"帐户","Public profile":"公开资料","Public name":"公开名称","Bio":"简介","Website":"HTTPS 网站","Save profile":"保存资料","Save privacy":"保存隐私设置","Visibility":"可见性","Public":"公开","Private":"私密","Repositories":"代码仓库","Followers":"关注者","Following":"正在关注","Create license":"创建许可证","Linked devices":"已绑定设备","Open panel":"打开面板","Browser preferences":"浏览器偏好","Reset preferences":"重置偏好","Package security":"软件包安全","Static analysis":"静态分析","GitHub star":"GitHub 星标"},
    "ru": {"Profile":"Профиль","Licenses":"Лицензии","Devices":"Устройства","Privacy":"Конфиденциальность","Invalid packages":"Недействительные пакеты","Preferences":"Настройки","Back to catalog":"Вернуться в каталог","Account":"Учетная запись","Public profile":"Публичный профиль","Public name":"Публичное имя","Bio":"Биография","Website":"Сайт HTTPS","Save profile":"Сохранить профиль","Save privacy":"Сохранить конфиденциальность","Visibility":"Видимость","Public":"Публичный","Private":"Приватный","Repositories":"Репозитории","Followers":"Подписчики","Following":"Подписки","Create license":"Создать лицензию","Linked devices":"Привязанные устройства","Open panel":"Открыть панель","Browser preferences":"Настройки браузера","Reset preferences":"Сбросить настройки","Package security":"Безопасность пакета","Static analysis":"Статический анализ","GitHub star":"Звезда GitHub"},
    "ar": {"Profile":"الملف الشخصي","Licenses":"التراخيص","Devices":"الأجهزة","Privacy":"الخصوصية","Invalid packages":"الحزم غير الصالحة","Preferences":"التفضيلات","Back to catalog":"العودة إلى الكتالوج","Account":"الحساب","Public profile":"الملف العام","Public name":"الاسم العام","Bio":"السيرة الذاتية","Website":"موقع HTTPS","Save profile":"حفظ الملف الشخصي","Save privacy":"حفظ الخصوصية","Visibility":"الرؤية","Public":"عام","Private":"خاص","Repositories":"المستودعات","Followers":"المتابعون","Following":"المتابَعون","Create license":"إنشاء ترخيص","Linked devices":"الأجهزة المرتبطة","Open panel":"فتح اللوحة","Browser preferences":"تفضيلات المتصفح","Reset preferences":"إعادة ضبط التفضيلات","Package security":"أمان الحزمة","Static analysis":"التحليل الثابت","GitHub star":"نجمة GitHub"},
    "hi": {"Profile":"प्रोफ़ाइल","Licenses":"लाइसेंस","Devices":"डिवाइस","Privacy":"गोपनीयता","Invalid packages":"अमान्य पैकेज","Preferences":"प्राथमिकताएँ","Back to catalog":"कैटलॉग पर वापस जाएँ","Account":"खाता","Public profile":"सार्वजनिक प्रोफ़ाइल","Public name":"सार्वजनिक नाम","Bio":"परिचय","Website":"HTTPS वेबसाइट","Save profile":"प्रोफ़ाइल सहेजें","Save privacy":"गोपनीयता सहेजें","Visibility":"दृश्यता","Public":"सार्वजनिक","Private":"निजी","Repositories":"रिपॉज़िटरी","Followers":"फ़ॉलोअर","Following":"फ़ॉलो किए गए","Create license":"लाइसेंस बनाएँ","Linked devices":"लिंक किए गए डिवाइस","Open panel":"पैनल खोलें","Browser preferences":"ब्राउज़र प्राथमिकताएँ","Reset preferences":"प्राथमिकताएँ रीसेट करें","Package security":"पैकेज सुरक्षा","Static analysis":"स्थिर विश्लेषण","GitHub star":"GitHub स्टार"},
    "tr": {"Profile":"Profil","Licenses":"Lisanslar","Devices":"Cihazlar","Privacy":"Gizlilik","Invalid packages":"Geçersiz paketler","Preferences":"Tercihler","Back to catalog":"Kataloğa dön","Account":"Hesap","Public profile":"Herkese açık profil","Public name":"Genel ad","Bio":"Biyografi","Website":"HTTPS web sitesi","Save profile":"Profili kaydet","Save privacy":"Gizliliği kaydet","Visibility":"Görünürlük","Public":"Herkese açık","Private":"Özel","Repositories":"Depolar","Followers":"Takipçiler","Following":"Takip edilenler","Create license":"Lisans oluştur","Linked devices":"Bağlı cihazlar","Open panel":"Paneli aç","Browser preferences":"Tarayıcı tercihleri","Reset preferences":"Tercihleri sıfırla","Package security":"Paket güvenliği","Static analysis":"Statik analiz","GitHub star":"GitHub yıldızı"},
    "pl": {"Profile":"Profil","Licenses":"Licencje","Devices":"Urządzenia","Privacy":"Prywatność","Invalid packages":"Nieprawidłowe pakiety","Preferences":"Preferencje","Back to catalog":"Wróć do katalogu","Account":"Konto","Public profile":"Profil publiczny","Public name":"Nazwa publiczna","Bio":"Biografia","Website":"Strona HTTPS","Save profile":"Zapisz profil","Save privacy":"Zapisz prywatność","Visibility":"Widoczność","Public":"Publiczne","Private":"Prywatne","Repositories":"Repozytoria","Followers":"Obserwujący","Following":"Obserwowani","Create license":"Utwórz licencję","Linked devices":"Połączone urządzenia","Open panel":"Otwórz panel","Browser preferences":"Preferencje przeglądarki","Reset preferences":"Zresetuj preferencje","Package security":"Bezpieczeństwo pakietu","Static analysis":"Analiza statyczna","GitHub star":"Gwiazda GitHub"},
    "uk": {"Profile":"Профіль","Licenses":"Ліцензії","Devices":"Пристрої","Privacy":"Конфіденційність","Invalid packages":"Недійсні пакети","Preferences":"Налаштування","Back to catalog":"Повернутися до каталогу","Account":"Обліковий запис","Public profile":"Публічний профіль","Public name":"Публічне ім’я","Bio":"Біографія","Website":"HTTPS-сайт","Save profile":"Зберегти профіль","Save privacy":"Зберегти приватність","Visibility":"Видимість","Public":"Публічний","Private":"Приватний","Repositories":"Репозиторії","Followers":"Підписники","Following":"Підписки","Create license":"Створити ліцензію","Linked devices":"Прив’язані пристрої","Open panel":"Відкрити панель","Browser preferences":"Налаштування браузера","Reset preferences":"Скинути налаштування","Package security":"Безпека пакета","Static analysis":"Статичний аналіз","GitHub star":"Зірка GitHub"},
}
for _locale, _strings in COMMON_TRANSLATIONS.items():
    TRANSLATIONS.setdefault(_locale, {}).update(_strings)

_LANDING_CATALOG = Path(__file__).with_name("landing_translations.json")
if _LANDING_CATALOG.exists():
    try:
        _landing_data = json.loads(_LANDING_CATALOG.read_text(encoding="utf-8"))
        for _locale, _strings in _landing_data.items():
            if _locale in SUPPORTED_LOCALES and isinstance(_strings, dict):
                TRANSLATIONS.setdefault(_locale, {}).update({str(k): str(v) for k, v in _strings.items()})
    except (OSError, ValueError, TypeError):
        pass


def normalize_locale(value: str | None) -> str | None:
    if not value:
        return None
    value = value.replace("_", "-").strip()
    if value in SUPPORTED_LOCALES:
        return value
    base = value.split("-", 1)[0].lower()
    aliases = {"zh": "zh-CN", "cmn": "zh-CN", "iw": "ar", "in": "hi"}
    return aliases.get(base, base if base in SUPPORTED_LOCALES else None)


def language_from_accept_language(header: str | None) -> str | None:
    candidates: list[tuple[float, str]] = []
    for item in (header or "").split(","):
        bits = item.strip().split(";q=")
        locale = normalize_locale(bits[0])
        if not locale:
            continue
        try:
            quality = float(bits[1]) if len(bits) > 1 else 1.0
        except ValueError:
            quality = 0.0
        candidates.append((quality, locale))
    return max(candidates, default=(0.0, None))[1]


@lru_cache(maxsize=256)
def locale_from_ip(ip: str | None, country_hint: str | None = None) -> str | None:
    country = (country_hint or "").upper()
    if country in COUNTRY_TO_LOCALE:
        return COUNTRY_TO_LOCALE[country]
    if not ip or ip in {"127.0.0.1", "::1"} or ip.startswith(("10.", "192.168.", "172.")):
        return None
    try:
        response = requests.get(f"https://ipwho.is/{ip}", timeout=1.5)
        data: dict[str, Any] = response.json() if response.ok else {}
        return COUNTRY_TO_LOCALE.get(str(data.get("country_code", "")).upper())
    except (requests.RequestException, ValueError, TypeError):
        return None


def resolve_locale(request: Request) -> str:
    explicit = normalize_locale(request.args.get("lang"))
    if explicit:
        return explicit
    cookie = normalize_locale(request.cookies.get(COOKIE_NAME))
    if cookie:
        return cookie
    detected = locale_from_ip(request.headers.get("X-Forwarded-For", request.remote_addr), request.headers.get("CF-IPCountry"))
    return detected or language_from_accept_language(request.headers.get("Accept-Language")) or DEFAULT_LOCALE


def translate(key: str, locale: str = DEFAULT_LOCALE, **values: Any) -> str:
    locale = normalize_locale(locale) or DEFAULT_LOCALE
    text = TRANSLATIONS.get(locale, {}).get(key) or TRANSLATIONS["es"].get(key) or key
    return text.format(**values) if values else text


def catalog() -> str:
    return json.dumps(SUPPORTED_LOCALES, ensure_ascii=False)
