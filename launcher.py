#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Launcher simple pour l'application Gestion Entreprise Pro
"""

import webview
import threading
import time
import sys
import os

# Forcer l'encodage UTF-8
if sys.platform == 'win32':
    import locale
    if sys.stdout.encoding != 'utf-8':
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')

# Configuration
APP_NAME = "Gestion Entreprise Pro"
FLASK_PORT = 5555

def start_flask():
    """Démarre Flask"""
    # Déterminer le répertoire de base
    if getattr(sys, 'frozen', False):
        # Exécuté depuis le .exe
        base_path = os.path.dirname(sys.executable)
    else:
        # Exécuté depuis Python
        base_path = os.path.dirname(os.path.abspath(__file__))

    # Ajouter au path Python
    if base_path not in sys.path:
        sys.path.insert(0, base_path)

    # Changer le répertoire de travail
    os.chdir(base_path)

    # Configurer les variables d'environnement pour Flask
    os.environ['FLASK_APP'] = 'app.py'

    # Importer l'app Flask
    import app as flask_app

    # Configurer les chemins des templates et static si nécessaire
    if getattr(sys, 'frozen', False):
        # En mode .exe, s'assurer que Flask utilise les bons chemins
        flask_app.app.template_folder = os.path.join(base_path, 'templates')
        flask_app.app.static_folder = os.path.join(base_path, 'static')

    # Lancer Flask
    flask_app.app.run(
        host='127.0.0.1',
        port=FLASK_PORT,
        debug=False,
        use_reloader=False,
        threaded=True
    )

def wait_for_server():
    """Attend que le serveur soit prêt"""
    import socket

    for _ in range(60):  # 30 secondes max
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(1)
            result = sock.connect_ex(('127.0.0.1', FLASK_PORT))
            sock.close()

            if result == 0:
                return True
        except:
            pass

        time.sleep(0.5)

    return False

def main():
    """Fonction principale"""
    # Démarrer Flask dans un thread
    flask_thread = threading.Thread(target=start_flask, daemon=True)
    flask_thread.start()

    # Attendre que Flask soit prêt
    if not wait_for_server():
        print("Erreur: Impossible de demarrer le serveur")
        sys.exit(1)

    # Créer la fenêtre
    webview.create_window(
        title=APP_NAME,
        url=f'http://127.0.0.1:{FLASK_PORT}',
        width=1400,
        height=900,
        resizable=True,
        min_size=(1000, 600)
    )

    # Démarrer l'interface
    webview.start()

if __name__ == '__main__':
    main()
