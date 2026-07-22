from flask import Flask, render_template, redirect, url_for, session, request, jsonify
from flask_dance.contrib.github import make_github_blueprint, github
from werkzeug.middleware.proxy_fix import ProxyFix
import os
from config import Config
import services

app = Flask(__name__)
# Aplicar ProxyFix para que Flask entienda que está detrás de un proxy (Render)
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)
app.config.from_object(Config)

# Configuración de GitHub OAuth
# Nota: Los scopes deben ser exactos. 'user:email' y 'repo' son correctos.
# Si el error persiste, asegúrate de que tu App en GitHub tenga permisos para estos scopes.
github_bp = make_github_blueprint(
    client_id=Config.GITHUB_OAUTH_CLIENT_ID,
    client_secret=Config.GITHUB_OAUTH_CLIENT_SECRET,
    scope=["user:email", "repo"], # Usar lista para mayor compatibilidad
    redirect_to="index"
)
app.register_blueprint(github_bp, url_prefix="/login")

# Configurar la redirect_uri explícita si se proporciona en variables de entorno
# IMPORTANTE: Flask-Dance usa 'redirect_url' internamente en la sesión si se pre-configura
redirect_uri = os.environ.get('GITHUB_OAUTH_REDIRECT_URI', None)
if redirect_uri:
    # Forzar la redirect_uri en el blueprint para que se use en todas las peticiones
    github_bp.session.redirect_uri = redirect_uri
    # También asegurar que el generador de URL la use
    os.environ['OAUTHLIB_RELAX_TOKEN_SCOPE'] = '1' # Ayuda si GitHub devuelve scopes ligeramente diferentes

# Forzar HTTPS en Flask-Dance para entornos de producción como Render
os.environ['OAUTHLIB_INSECURE_TRANSPORT'] = '1' # Solo para pruebas locales si fuera necesario, pero en Render usaremos ProxyFix
os.environ['PREFERRED_URL_SCHEME'] = 'https'

@app.context_processor
def inject_github():
    return dict(github=github)

@app.route("/")
def index():
    if not github.authorized:
        return redirect(url_for("login"))
    
    # Verificar si completó el paso 2 (Telegram)
    if not session.get("telegram_user"):
        return redirect(url_for("onboarding_step2"))
        
    # El catálogo principal se lee de ismyself de JesusQuijada34
    catalog = services.get_catalog("JesusQuijada34")
    return render_template("index.html", packages=catalog.get("packages", []))

@app.route("/onboarding/step2")
def onboarding_step2():
    if not github.authorized:
        return redirect(url_for("login"))
    if session.get("telegram_user"):
        return redirect(url_for("index"))
    
    try:
        resp = github.get("/user")
        if not resp.ok:
            return redirect(url_for("logout"))
        github_username = resp.json().get("login")
        if not github_username:
            return redirect(url_for("logout"))
    except Exception:
        return redirect(url_for("logout"))
        
    return render_template("onboarding_telegram.html", github_username=github_username, telegram_bot_username=Config.TELEGRAM_BOT_USERNAME)

@app.route("/api/telegram_callback")
def telegram_callback():
    auth_data = request.args.to_dict()
    if auth_data.get("id"):
        session["telegram_user"] = auth_data
        resp = github.get("/user")
        github_username = resp.json()["login"]
        services.link_telegram_to_github(github_username, auth_data)
        return redirect(url_for("my_profile"))
    return redirect(url_for("onboarding_step2"))

@app.route("/api/generate_mirror/<package_name>/<platform>")
def generate_mirror(package_name, platform):
    if not github.authorized or not session.get("telegram_user"):
        return jsonify({"error": "Debes completar el onboarding para descargar"}), 401
    
    # Lógica de cifrado de mirrors
    import hashlib
    import time
    token = hashlib.sha256(f"{package_name}{platform}{time.time()}".encode()).hexdigest()[:16]
    mirror_url = f"https://mirror-crypted.foundstore.im/dl/{package_name}/{platform}?t={token}"
    
    return jsonify({"mirror_url": mirror_url})

@app.route("/global")
def global_packages():
    """
    Tienda global: descubre y muestra los paquetes Fluthin (.iflapp) de
    TODOS los desarrolladores (misma lógica de identificación que
    jesusquijada34.netlify.app), sin importar la plataforma que estén
    visitando el sitio.
    Soporta filtro por autor via ?author=<username> (case-insensitive).
    """
    visitor_platform = services.detect_platform_key(request.headers.get("User-Agent"))
    author_filter = request.args.get("author", "").strip()

    if author_filter:
        apps = services.get_packages_by_author(author_filter)
    else:
        apps = services.get_global_fluthin_catalog()

    authors = services.get_all_authors()
    return render_template(
        "global_packages.html",
        apps=apps,
        authors=authors,
        author_filter=author_filter,
        visitor_platform=visitor_platform,
        visitor_category=services.PLATFORM_TO_CATEGORY.get(visitor_platform, "Otros"),
    )


@app.route("/author/<username>")
def author_packages(username):
    """
    Página dedicada para un autor concreto. Muestra todos sus paquetes
    Fluthin con la misma UI que /global, pero filtrada y con cabecera
    de autor visible.
    """
    if not username or len(username) > 64:
        abort(404)
    visitor_platform = services.detect_platform_key(request.headers.get("User-Agent"))
    apps = services.get_packages_by_author(username)

    if not apps:
        # Distinguimos "no existe" de "existe pero sin paquetes" solo si
        # el autor aparece en la lista global de autores conocidos
        known = {a["username"].lower() for a in services.get_all_authors()}
        if username.lower() not in known:
            abort(404)

    return render_template(
        "author_packages.html",
        author=username,
        apps=apps,
        visitor_platform=visitor_platform,
        visitor_category=services.PLATFORM_TO_CATEGORY.get(visitor_platform, "Otros"),
    )


@app.route("/api/global_download/<path:repo>")
def api_global_download(repo):
    """
    Resuelve la descarga correcta para el visitante actual según su
    plataforma (Windows/Linux/Mac/otros), igual que packagemaker
    (rama render) hace al generar releases por plataforma.
    """
    package_name = request.args.get("package_name")
    result = services.resolve_download_for_visitor(
        repo, request.headers.get("User-Agent"), package_name=package_name
    )
    return jsonify(result)


@app.route("/api/global_catalog")
def api_global_catalog():
    force = request.args.get("refresh") == "1"
    return jsonify({"apps": services.get_global_fluthin_catalog(force_refresh=force)})


@app.route("/help")
def help_page():
    return render_template("help.html")

@app.route("/login")
def login():
    if github.authorized:
        return redirect(url_for("index"))
    return render_template("login.html")

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("index"))

@app.route("/<username>/")
@app.route("/<username>/repo/")
def developer_profile(username):
    # Verificar si es una cuenta ondev
    ondev_accounts = services.load_ondev_accounts()
    is_ondev = username in ondev_accounts
    
    # Intentar cargar perfil y catálogo
    profile_data = services.get_github_user_profile(username)
    local_profile = services.get_local_profile(username)
    if local_profile:
        profile_data = local_profile
        
    user_catalog = services.get_catalog(username)
    
    if not profile_data and not is_ondev:
        return render_template("error.html", message="Usuario no encontrado o sin perfil público."), 404
    
    # Obtener datos de seguidores de la DB local
    user_data = ondev_accounts.get(username, {"followers": [], "following": []})
    
    # Verificar si el usuario actual sigue a este perfil
    is_following = False
    if github.authorized:
        curr_resp = github.get("/user")
        if curr_resp.ok:
            curr_user = curr_resp.json()["login"]
            is_following = curr_user in user_data.get("followers", [])

    return render_template("developer_profile.html", 
                           username=username, 
                           profile=profile_data, 
                           packages=user_catalog.get("packages", []),
                           is_ondev=is_ondev,
                           follower_count=len(user_data.get("followers", [])),
                           following_count=len(user_data.get("following", [])),
                           is_following=is_following)

@app.route("/packages/<package_name>/")
def package_detail(package_name):
    catalog = services.get_catalog()
    package = next((p for p in catalog.get("packages", []) if p["name"] == package_name), None)

    if not package:
        return render_template("error.html", message="Paquete no encontrado."), 404

    return render_template("package_detail.html", package=package)


@app.route("/package/<package_name>")
def package_detail_global(package_name):
    """
    Detalle de un paquete del catalogo global Fluthin.
    Lo busca por <packagename> (el campo <app> del details.xml)
    entre todos los repos del catalogo.
    """
    apps = services.get_global_fluthin_catalog()
    app_match = next((a for a in apps if a.get("packagename") == package_name), None)

    if not app_match:
        return render_template("error.html", message="Paquete no encontrado en el catalogo global."), 404

    visitor_platform = services.detect_platform_key(request.headers.get("User-Agent"))
    return render_template(
        "package_detail.html",
        app=app_match,
        visitor_platform=visitor_platform,
        visitor_category=services.PLATFORM_TO_CATEGORY.get(visitor_platform, "Otros"),
    )


@app.route("/health/mongo")
def health_mongo():
    """
    Diagnostico de MongoDB. Devuelve JSON con el estado actual
    y reintenta la conexion si la anterior fallo. Util para debug
    en Render sin tener que reiniciar el servicio.
    """
    from flask import jsonify
    return jsonify(services.mongo_ping())


@app.route("/health")
def health():
    """Health check basico del servicio."""
    from flask import jsonify
    return jsonify({
        "status": "ok",
        "mongo": services._mongo_status,
    })

@app.route("/me/edit", methods=["GET", "POST"])
def edit_profile():
    if not github.authorized:
        return redirect(url_for("github.login"))
    
    resp = github.get("/user")
    username = resp.json()["login"]
    
    if request.method == "POST":
        # Procesar el formulario
        links = []
        names = request.form.getlist("link_name[]")
        urls = request.form.getlist("link_url[]")
        for n, u in zip(names, urls):
            if n and u:
                links.append({"name": n, "url": u})
        
        updated_profile = {
            "name": request.form.get("name"),
            "description": request.form.get("description"),
            "logo": request.form.get("logo"),
            "banner": request.form.get("banner"),
            "links": links
        }
        
        # Guardar localmente
        services.update_local_profile(username, updated_profile)
        return redirect(url_for("my_profile"))

    # Cargar datos actuales
    profile_data = services.get_github_user_profile(username)
    # Si hay cambios locales, priorizarlos (puedes implementar esto en services)
    local_profile = services.get_local_profile(username)
    if local_profile:
        profile_data = local_profile

    return render_template("edit_profile.html", username=username, profile=profile_data)

@app.route("/me")
def my_profile():
    if not github.authorized:
        return redirect(url_for("github.login"))
    
    resp = github.get("/user")
    if not resp.ok:
        return "Error obteniendo información de GitHub", 500
    
    username = resp.json()["login"]
    ondev_accounts = services.load_ondev_accounts()
    is_ondev = username in ondev_accounts
    
    # Cargar perfil y catálogo
    profile_data = services.get_github_user_profile(username)
    local_profile = services.get_local_profile(username)
    if local_profile:
        profile_data = local_profile
        
    user_catalog = services.get_catalog(username)
    user_data = ondev_accounts.get(username, {"followers": [], "following": []})
    
    return render_template("user_profile.html", 
                           username=username, 
                           profile=profile_data, 
                           packages=user_catalog.get("packages", []),
                           is_ondev=is_ondev,
                           follower_count=len(user_data.get("followers", [])),
                           following_count=len(user_data.get("following", [])),
                           package_count=len(user_catalog.get("packages", [])))

@app.route("/panel")
def ondev_panel():
    if not github.authorized:
        return redirect(url_for("github.login"))
    
    resp = github.get("/user")
    if not resp.ok:
        return "Error obteniendo información de GitHub", 500
    
    username = resp.json()["login"]
    ondev_accounts = services.load_ondev_accounts()
    
    if username not in ondev_accounts:
        return render_template("error.html", message="No tienes acceso al panel profesional."), 403
    
    return render_template("ondev_panel.html", account=ondev_accounts[username])

@app.route("/api/register_ondev", methods=["POST"])
def register_ondev():
    if not github.authorized:
        return jsonify({"error": "No autorizado"}), 401
    
    resp = github.get("/user")
    username = resp.json()["login"]
    
    account_data = {
        "github_username": username,
        "is_ondev": True,
        "packages": []
    }
    services.save_ondev_account(account_data)
    return jsonify({"success": True})

@app.route("/api/follow/<target_username>", methods=["POST"])
def follow_user(target_username):
    if not github.authorized:
        return jsonify({"error": "Debes iniciar sesión para seguir creadores"}), 401
    
    resp = github.get("/user")
    follower_username = resp.json()["login"]
    
    if follower_username == target_username:
        return jsonify({"error": "No puedes seguirte a ti mismo"}), 400
    
    action, count = services.toggle_follow(follower_username, target_username)
    return jsonify({"action": action, "follower_count": count})

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    app.run(host="0.0.0.0", port=port, debug=True)