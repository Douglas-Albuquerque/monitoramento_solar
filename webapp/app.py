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

USINA_URLS = {
    "UFV CASA 4": "https://home.solarmanpv.com/plant/infos/data",
    "UFV-ATLANTA": "http://server.growatt.com",
    "UFV-HELENA-1": "http://server.growatt.com",
    "UFV HELENA-2": "https://web3.isolarcloud.com.hk/#/plantList",
}

app = Flask(__name__)


def verificar_expiracao_cookies_web():
    """Retorna info de expiração dos cookies do Solarman."""
    cookie_path = os.path.join(BASE_DIR, "cookies", "cookies_solarman.pkl")

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
        unix_socket="/var/run/mysqld/mysqld.sock",
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

    info_extra = {
        "UFV-ATLANTA": {
            "descricao": "Atlanta SEDE",
            "maps_url": os.getenv("MAPS_UFV_ATLANTA", ""),
        },
        "UFV CASA 4": {
            "descricao": "Casa Mardonio",
            "maps_url": os.getenv("MAPS_UFV_CASA4", ""),
        },
        "UFV-HELENA-1": {
            "descricao": "Lado Casa Mardonio",
            "maps_url": os.getenv("MAPS_UFV_HELENA1", ""),
        },
        "UFV HELENA-2": {
            "descricao": "Galpões",
            "maps_url": os.getenv("MAPS_UFV_HELENA2", ""),
        },
    }

    for u in usinas:
        nome = u.get("nome_usina")
        u["url_monitor"] = USINA_URLS.get(nome)
        # if isinstance(u.get("updated_at"), datetime):
        #    continue
        extra = info_extra.get(nome, {})
        u["descricao"] = extra.get("descricao", "")
        u["maps_url"] = extra.get("maps_url", "")
    # Verificar cookies Solarman
    cookies_info = verificar_expiracao_cookies_web()

    return render_template("index.html", usinas=usinas, cookies_info=cookies_info)


if __name__ == "__main__":
    # dev: porta 5000 aberta em todas interfaces
    app.run(host="0.0.0.0", port=5000, debug=True)
