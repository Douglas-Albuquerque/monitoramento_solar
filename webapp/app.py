import os
import json
import base64
import pickle
from datetime import datetime

from flask import Flask, render_template
from dotenv import load_dotenv
import mysql.connector

# Caminho do .env (na raiz do projeto: ~/solar-dashboard/.env)
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENV_PATH = os.path.join(BASE_DIR, ".env")
load_dotenv(ENV_PATH)

app = Flask(__name__)


def verificar_expiracao_cookies_web():
    """Retorna info de expiração dos cookies do Solarman."""
    cookie_path = os.path.join(BASE_DIR, "cookies_solarman.pkl")

    if not os.path.exists(cookie_path):
        return None

    try:
        with open(cookie_path, "rb") as f:
            cookies = pickle.load(f)

        for cookie in cookies:
            if "value" in cookie and cookie["value"].startswith("eyJ"):
                try:
                    payload_b64 = cookie["value"].split(".")[1]
                    payload_b64 += "=" * (4 - len(payload_b64) % 4)
                    payload_json = base64.b64decode(payload_b64).decode("utf-8")
                    payload = json.loads(payload_json)

                    if "exp" in payload:
                        exp_timestamp = payload["exp"]
                        exp_date = datetime.fromtimestamp(exp_timestamp)
                        agora = datetime.now()
                        dias_restantes = (exp_date - agora).days

                        return {
                            "dias_restantes": dias_restantes,
                            "expira_em": exp_date.strftime("%d/%m/%Y"),
                            "cor": (
                                "success"
                                if dias_restantes > 10
                                else ("warning" if dias_restantes > 5 else "danger")
                            ),
                        }
                except:
                    continue
    except:
        pass

    return None


def get_db_connection():
    return mysql.connector.connect(
        host=os.getenv("DB_HOST", "localhost"),
        user=os.getenv("DB_USER", "solar_user"),
        password=os.getenv("DB_PASS"),
        database=os.getenv("DB_NAME", "solar_monitor"),
    )


def get_status_usinas():
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    cur.execute(
        """
        SELECT nome_usina, status, updated_at
        FROM usinas_status
        ORDER BY nome_usina
        """
    )
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return rows


@app.route("/")
def dashboard():
    usinas = get_status_usinas()
    for u in usinas:
        if isinstance(u.get("updated_at"), datetime):
            continue

    # Verificar cookies Solarman
    cookies_info = verificar_expiracao_cookies_web()

    return render_template("index.html", usinas=usinas, cookies_info=cookies_info)


if __name__ == "__main__":
    # dev: porta 5000 aberta em todas interfaces
    app.run(host="0.0.0.0", port=5000, debug=True)
