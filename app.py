from flask import Flask, render_template, redirect, url_for, session, request, jsonify
from flask_dance.contrib.github import make_github_blueprint, github
import os
from config import Config
import services

app = Flask(__name__)
app.config.from_object(Config)

# Configuración de GitHub OAuth
github_bp = make_github_blueprint(
    client_id=Config.GITHUB_OAUTH_CLIENT_ID,
    client_secret=Config.GITHUB_OAUTH_CLIENT_SECRET,
)
app.register_blueprint(github_bp, url_prefix="/login")

@app.route("/")
def index():
    if not github.authorized:
        return redirect(url_for("login"))
    # El catálogo principal se lee de ismyself de JesusQuijada34
    catalog = services.get_catalog("JesusQuijada34")
    return render_template("index.html", packages=catalog.get("packages", []))

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
