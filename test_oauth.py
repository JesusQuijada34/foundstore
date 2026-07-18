#!/usr/bin/env python3
import os
from dotenv import load_dotenv
from flask import Flask
from flask_dance.contrib.github import make_github_blueprint

load_dotenv()

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'test')

github_bp = make_github_blueprint(
    client_id=os.environ.get('GITHUB_OAUTH_CLIENT_ID'),
    client_secret=os.environ.get('GITHUB_OAUTH_CLIENT_SECRET'),
    scope="user:email,repo",
    redirect_to="index"
)

redirect_uri = os.environ.get('GITHUB_OAUTH_REDIRECT_URI', None)
if redirect_uri:
    github_bp.session.redirect_uri = redirect_uri
    print(f"✓ Redirect URI configurada: {redirect_uri}")
else:
    print("✗ No hay redirect_uri configurada")

# Verificar la configuración del cliente OAuth
print(f"Client ID: {github_bp.session.client_id}")
print(f"Redirect URI en sesión: {getattr(github_bp.session, 'redirect_uri', 'No configurada')}")
