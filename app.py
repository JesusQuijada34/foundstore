from flask import Flask, render_template, redirect, url_for, session, request, jsonify, Response, stream_with_context, abort
from flask_dance.contrib.github import make_github_blueprint, github
from werkzeug.middleware.proxy_fix import ProxyFix
import os
import time
from config import Config
import services
import notifications
import storage

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


def _current_github_username():
    """Devuelve el username de GitHub del usuario actual, o None."""
    cached = session.get("github_username")
    if cached:
        return cached
    try:
        if not github.authorized:
            return None
        resp = github.get("/user")
        if not resp.ok:
            return None
        uname = resp.json().get("login")
        if uname:
            session["github_username"] = uname
        return uname
    except Exception:
        return None


def _telegram_verified():
    """Devuelve True si el usuario tiene sesion verificada con Telegram (24h)."""
    data = session.get("telegram_verified") or {}
    exp = data.get("expires_at", 0)
    if exp < time.time():
        return False
    return data.get("verified") is True


def _mark_telegram_verified():
    session["telegram_verified"] = {
        "verified": True,
        "at": time.time(),
        "expires_at": time.time() + notifications.VERIFIED_TTL_SECONDS,
    }


@app.context_processor
def inject_globals():
    """
    Inyecta variables globales a TODOS los templates, en particular:
    - github: el blueprint (para chequeos .authorized)
    - github_username: el login actual (o vacio)
    - telegram_user: la sesion de Telegram del onboarding paso 2
    - telegram_verified: True si el usuario ya paso la verificacion con code
    """
    return dict(
        github=github,
        github_username=session.get("github_username") or "",
        telegram_user=session.get("telegram_user") or None,
        telegram_verified=_telegram_verified(),
    )

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


# =====================================================================
# AUTENTICACION CON CODIGO DE TELEGRAM (v2 - MongoDB + storage.py)
# =====================================================================
# Flujo:
#   1) Usuario va a /settings y pulsa "Vincular Telegram"
#   2) /api/auth/request_code (POST) genera codigo OTP en MongoDB con TTL
#   3) Se le muestra el codigo + instrucciones para ir al bot
#   4) El bot recibe el codigo (en su muro de auth), lo valida contra Mongo
#      y vincula la cuenta telegram_id -> github_username
#   5) El bot notifica via notify_user() -> SSE empuja evento a la web
#   6) La web actualiza el estado en tiempo real
# =====================================================================

LINK_CODE_TTL = 300  # 5 minutos


@app.route("/api/auth/request_code", methods=["POST"])
def api_request_code():
    if not github.authorized:
        return jsonify({"error": "Necesitas iniciar sesion con GitHub primero."}), 401
    username = _current_github_username()
    if not username:
        return jsonify({"error": "Sesion de GitHub invalida."}), 401

    if not storage.mongo.ok:
        return jsonify({
            "error": "storage_unavailable",
            "message": "La vinculacion requiere MongoDB. Revisa /health/mongo.",
        }), 503

    # Si ya esta vinculado, devolver estado actual
    status = storage.get_link_status(username)
    if status.get("is_active") and status.get("telegram_id"):
        return jsonify({
            "ok": True,
            "already_linked": True,
            "telegram_username": status.get("telegram_username"),
        })

    # Crear OTP
    otp = storage.create_otp(username, ttl_seconds=LINK_CODE_TTL)
    if not otp:
        return jsonify({"error": "no_se_pudo_generar_codigo"}), 500

    return jsonify({
        "ok": True,
        "code": otp["code"],
        "expires_at": otp["expires_at"],
        "ttl": otp["ttl"],
        "bot_username": Config.TELEGRAM_BOT_USERNAME,
        "web_url": request.host_url.rstrip("/"),
        "instructions": (
            f"Abre Telegram, busca @{Config.TELEGRAM_BOT_USERNAME} y "
            f"escribe el siguiente codigo:"
        ),
    })


@app.route("/api/auth/verify_code", methods=["POST"])
def api_verify_code():
    """
    Endpoint legacy: la vinculacion real la hace el bot al validar el codigo.
    Este endpoint solo sirve para que el frontend pueda POLL el estado.
    Mantenido por compatibilidad - el flujo real es bot-driven.
    """
    if not github.authorized:
        return jsonify({"error": "auth_required"}), 401
    username = _current_github_username()
    if not username:
        return jsonify({"error": "auth_required"}), 401

    # La vinculacion la hace el bot. Aqui solo informamos del estado.
    status = storage.get_link_status(username)
    return jsonify({
        "ok": True,
        "verified": bool(status.get("is_active") and status.get("telegram_id")),
        "telegram_username": status.get("telegram_username"),
        "telegram_name": status.get("telegram_name"),
        "linked_at": status.get("linked_at"),
    })


@app.route("/api/auth/unlink", methods=["POST"])
def api_unlink_telegram():
    if not github.authorized:
        return jsonify({"error": "auth_required"}), 401
    username = _current_github_username()
    if not username:
        return jsonify({"error": "auth_required"}), 401

    if not storage.mongo.ok:
        return jsonify({"error": "storage_unavailable"}), 503

    ok = storage.unlink_telegram(username)
    if ok:
        # Invalidar sesion local tambien
        session.pop("telegram_user", None)
        session.pop("telegram_verified", None)
        # Empujar notificacion
        notifications.notify_user(
            username,
            title="Telegram desvinculado",
            desc="La vinculacion con Telegram se ha eliminado. Puedes volver a vincular cuando quieras.",
            icon="warning",
        )
        return jsonify({"ok": True})
    return jsonify({"error": "no_se_pudo_desvincular"}), 500


@app.route("/api/auth/link_status")
def api_link_status():
    """Estado completo de vinculacion para mostrar en /settings."""
    if not github.authorized:
        return jsonify({"logged_in": False}), 401
    username = _current_github_username() or ""
    if not username:
        return jsonify({"logged_in": False}), 401

    status = storage.get_link_status(username)
    active_otp = storage.get_active_otp(username)
    return jsonify({
        "logged_in": True,
        "github_username": username,
        "linked": bool(status.get("is_active") and status.get("telegram_id")),
        "telegram_id": status.get("telegram_id"),
        "telegram_username": status.get("telegram_username"),
        "telegram_name": status.get("telegram_name"),
        "linked_at": status.get("linked_at"),
        "active_otp": bool(active_otp),
        "otp_expires_at": active_otp.get("expires_at") if active_otp else None,
        "sessions": status.get("sessions", []),
    })


@app.route("/api/auth/code_status")
def api_code_status():
    """Dice al frontend si hay un codigo pendiente y si el usuario esta verificado."""
    if not github.authorized:
        return jsonify({"logged_in": False}), 401
    username = _current_github_username() or ""
    active = storage.get_active_otp(username)
    return jsonify({
        "logged_in": True,
        "github_username": username,
        "telegram_linked": bool(storage.get_user(username) and storage.get_user(username).get("telegram_id")),
        "pending_code": bool(active),
        "pending_code_expires_in": max(0, active["expires_at"] - int(time.time())) if active else 0,
    })


# =====================================================================
# /settings - configuracion del user (vincular/desvincular Telegram)
# =====================================================================

@app.route("/settings")
def settings():
    if not github.authorized:
        return redirect(url_for("login"))
    username = _current_github_username() or ""
    status = storage.get_link_status(username) if storage.mongo.ok else {}
    return render_template("settings.html", status=status, username=username)


# =====================================================================
# SSE - Server-Sent Events (notificaciones en tiempo real)
# =====================================================================

@app.route("/api/events")
def api_events():
    if not github.authorized:
        return jsonify({"error": "unauthorized"}), 401
    username = _current_github_username()
    if not username:
        return jsonify({"error": "unauthorized"}), 401

    @stream_with_context
    def generate():
        # Cabeceras SSE-friendly
        for chunk in notifications.stream_for(username):
            yield chunk

    return Response(generate(), mimetype="text/event-stream", headers={
        "Cache-Control": "no-cache",
        "X-Accel-Buffering": "no",
        "Connection": "keep-alive",
    })


# =====================================================================
# DESCARGA DE PAQUETES FLUTHIN (requiere sesion verificada con Telegram)
# =====================================================================

@app.route("/api/download_fluthin/<package_name>/<platform>")
def api_download_fluthin(package_name, platform):
    """
    Endpoint unificado de descarga. Sustituye a /api/global_download y
    /api/generate_mirror: decide segun la plataforma y requiere verificacion
    de Telegram.
    """
    if not github.authorized:
        return jsonify({"error": "auth_required", "message": "Inicia sesion con GitHub para descargar."}), 401
    username = _current_github_username()
    if not username:
        return jsonify({"error": "auth_required"}), 401

    if not _telegram_verified():
        return jsonify({
            "error": "telegram_verification_required",
            "message": "Verifica tu sesion con Telegram para poder descargar.",
        }), 403

    # Buscar el paquete en el catalogo global
    apps = services.get_global_fluthin_catalog()
    app_match = next((a for a in apps if a.get("packagename") == package_name), None)
    if not app_match:
        return jsonify({"error": "package_not_found"}), 404

    repo = app_match.get("repo")
    native = ["windows", "linux", "multi"]
    if platform in native:
        result = services.resolve_download_for_visitor(
            repo, request.headers.get("User-Agent"), package_name=package_name
        )
        # Si no hay build nativo pero el usuario esta verificado,
        # caemos al fluthin://
        return jsonify({
            "ok": True,
            "kind": "native" if result.get("direct_url") else "fluthin",
            "platform": result.get("category"),
            "release_tag": result.get("release_tag"),
            "direct_url": result.get("direct_url"),
            "asset_name": result.get("asset_name"),
            "fluthin_url": result.get("fluthin_url"),
        })

    # Plataformas no nativas: generamos un mirror cifrado local
    import hashlib
    token = hashlib.sha256(f"{package_name}{platform}{username}{time.time()}".encode()).hexdigest()[:16]
    mirror_url = f"https://mirror-crypted.foundstore.im/dl/{package_name}/{platform}?t={token}&u={username}"
    return jsonify({
        "ok": True,
        "kind": "mirror",
        "platform": platform,
        "mirror_url": mirror_url,
    })


# =====================================================================
# WEBHOOK DEL BOT DE TELEGRAM (recibe updates de Telegram)
# =====================================================================
# Activa esto con:  curl -X POST https://api.telegram.org/bot<TOKEN>/setWebhook \
#                       -d url=https://<tu-app>.onrender.com/api/telegram_webhook
# Y desactiva el polling con:  curl -X POST .../deleteWebhook
# =====================================================================

@app.route("/api/telegram_webhook", methods=["POST"])
def telegram_webhook():
    """
    Recibe updates de Telegram. Si el bot recibe el comando /code de un
    usuario que ya tiene cuenta vinculada a foundstore, le genera y manda
    el codigo de verificacion.
    Tambien procesa /start, /help y mensajes normales.
    """
    if not Config.TELEGRAM_BOT_TOKEN:
        return jsonify({"error": "bot not configured"}), 503

    update = request.get_json(silent=True) or {}
    message = update.get("message") or update.get("edited_message") or {}
    text = (message.get("text") or "").strip()
    telegram_user = message.get("from") or {}
    telegram_id = telegram_user.get("id")

    if not text or not telegram_id:
        return jsonify({"ok": True})

    # Buscar a que cuenta de foundstore esta vinculado este telegram_id
    accounts = services.load_ondev_accounts()
    linked_username = None
    for gh_user, data in accounts.items():
        if data.get("telegram_id") == telegram_id:
            linked_username = gh_user
            break

    def reply(msg):
        try:
            import requests as _req
            _req.post(
                f"https://api.telegram.org/bot{Config.TELEGRAM_BOT_TOKEN}/sendMessage",
                json={
                    "chat_id": telegram_id,
                    "text": msg,
                    "parse_mode": "Markdown",
                },
                timeout=5,
            )
        except Exception as e:
            print(f"[telegram_webhook] reply error: {e}")

    if text.startswith("/start"):
        reply(
            "👋 Hola! Soy el bot de foundstore.\n\n"
            "Comandos:\n"
            "/code - Genera un codigo de verificacion para descargar paquetes\n"
            "/help - Ver ayuda"
        )
    elif text.startswith("/help"):
        reply(
            "🤖 *foundstore bot*\n\n"
            "Para descargar paquetes Fluthin desde la web, primero vincula tu cuenta "
            "y luego escribe /code aqui. Te mandare un codigo de 6 digitos que tendras "
            "que escribir en la web para verificar la sesion.\n\n"
            "El codigo expira en 5 minutos."
        )
    elif text.startswith("/code"):
        if not linked_username:
            reply(
                "❌ No encuentro tu cuenta de GitHub vinculada.\n\n"
                "Ve a la web, inicia sesion y completa el paso 2 (vincular Telegram). "
                "Luego vuelve aqui y escribe /code."
            )
        else:
            code = notifications.issue_code(linked_username, telegram_id=telegram_id)
            reply(
                f"🔐 Tu codigo de verificacion es:\n\n"
                f"`{code}`\n\n"
                f"Cuenta: @{linked_username}\n"
                f"Expira en 5 minutos.\n\n"
                f"Escribelo en la web para activar las descargas."
            )
            # Empujar notificacion a la web
            notifications.notify_user(
                linked_username,
                title="Codigo enviado desde Telegram",
                desc=f"Revisa el chat con el bot. Codigo enviado.",
                icon="telegram",
            )
    else:
        # Mensaje normal: contestar con pista
        if linked_username:
            reply("💡 Escribe /code para generar un codigo de verificacion.")
        else:
            reply("👋 Hola! Escribe /code para empezar (primero vincula tu cuenta en la web).")

    return jsonify({"ok": True})


# =====================================================================
# HEALTH (movido aqui para tenerlo centralizado con el resto)
# =====================================================================

@app.route("/health")
def health():
    return jsonify({"status": "ok", "mongo": services._mongo_status})


@app.route("/health/mongo")
def health_mongo():
    return jsonify(services.mongo_ping())


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    app.run(host="0.0.0.0", port=port, debug=True)