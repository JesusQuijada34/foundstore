#!/usr/bin/env python3
"""
Servidor HTTP simple para desarrollo local
Ejecutar: python server.py
Luego abrir: http://localhost:8000
"""

import http.server
import socketserver
import os
import sys

PORT = 8000

class MyHTTPRequestHandler(http.server.SimpleHTTPRequestHandler):
    def end_headers(self):
        # Permitir CORS para desarrollo
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Cache-Control', 'no-store, no-cache, must-revalidate')
        super().end_headers()

    def log_message(self, format, *args):
        # Formato de log más limpio
        print(f"[{self.log_date_time_string()}] {format % args}")

def main():
    # Cambiar al directorio del script
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    
    Handler = MyHTTPRequestHandler
    
    try:
        with socketserver.TCPServer(("", PORT), Handler) as httpd:
            print(f"\n{'='*60}")
            print(f"🚀 Servidor iniciado en http://localhost:{PORT}")
            print(f"📁 Sirviendo archivos desde: {os.getcwd()}")
            print(f"{'='*60}\n")
            print("Presiona Ctrl+C para detener el servidor\n")
            httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n\n✅ Servidor detenido correctamente")
        sys.exit(0)
    except OSError as e:
        if e.errno == 98 or e.errno == 10048:  # Puerto en uso
            print(f"\n❌ Error: El puerto {PORT} ya está en uso")
            print(f"💡 Intenta cerrar otros servidores o usa otro puerto\n")
        else:
            print(f"\n❌ Error: {e}\n")
        sys.exit(1)

if __name__ == "__main__":
    main()
