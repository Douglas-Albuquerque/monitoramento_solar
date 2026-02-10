#!/usr/bin/env python3
"""
Robô Solar Dashboard - Coleta status das usinas e grava no MariaDB.
"""
import os
import base64
import json
import requests
import logging
from logging.handlers import RotatingFileHandler
from requests.exceptions import HTTPError
from datetime import datetime, timedelta, timezone

from dotenv import load_dotenv
import mysql.connector
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.chrome.options import Options
from selenium.common.exceptions import (
    TimeoutException,
    NoSuchElementException,
)  # [file:20]
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), "..", ".env"))

# Diretório e arquivo de log
LOG_DIR = os.path.join(os.path.dirname(__file__), "..", "logs")
os.makedirs(LOG_DIR, exist_ok=True)
LOG_FILE = os.path.join(LOG_DIR, "robo_status.log")

# Configuração básica de logging
logger = logging.getLogger("robo_solar")
logger.setLevel(logging.INFO)

# Evitar handlers duplicados
if not logger.handlers:
    # Log em arquivo com rotação
    file_handler = RotatingFileHandler(
        LOG_FILE, maxBytes=1_000_000, backupCount=5, encoding="utf-8"
    )
    formatter = logging.Formatter(
        "%(asctime)s - %(levelname)s - %(name)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    # Log no console (terminal)
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

# ========== CONFIGURAÇÃO DAS USINAS ==========
USINAS = [
    {
        "nome": "UFV-ATLANTA",
        "responsavel": "Edson - 85988066711",
        "tipo": "growatt_api",
        "plant_id": 310511,  # plant_id da API
        "token_env": "GROWATT_TOKEN_ATLANTA",
        "limite_kw_online": 0.1,  # >0.1 kW consideramos ONLINE
        # dados para fallback via Selenium (se quiser ativar depois):
        "url_login": "http://server.growatt.com",
        "usuario_env": "SITE1_USER",
        "senha_env": "SITE1_PASS",
        "user_sel": "input[name='username']",
        "pass_sel": "input[name='password']",
        "btn_sel": "button.hasColorBtn.loginB",
        "status_sel": "span.green",
        "online_texto": "connected",
    },
    {
        "nome": "UFV CASA 4",
        "responsavel": "Elizaldo - 85988858352",
        "url_dashboard": "https://home.solarmanpv.com/plant/infos/data",
        "usa_cookies": True,
        "cookie_file": "cookies/cookies_solarman.pkl",
        "status_sel": "span.station-status",
        "online_texto": "normal",
    },
    {
        "nome": "UFV-HELENA-1",
        "responsavel": "Elizaldo - 85988858352",
        "tipo": "growatt_api",
        "plant_id": 2480414,
        "token_env": "GROWATT_TOKEN_HELENA1",
        "limite_kw_online": 0.1,
        # fallback Selenium pode ser reativado depois se quiser:
        "url_login": "http://server.growatt.com",
        "usuario_env": "SITE3_USER",
        "senha_env": "SITE3_PASS",
        "user_sel": "input[name='username']",
        "pass_sel": "input[name='password']",
        "btn_sel": "button.hasColorBtn.loginB",
        "status_sel": "span.green",
        "online_texto": "connected",
    },
    {
        "nome": "UFV HELENA-2",
        "responsavel": "Edson - 85988066711",
        "url_login": "https://web3.isolarcloud.com.hk/#/login",
        "usuario_env": "SITE4_USER",
        "senha_env": "SITE4_PASS",
        "user_sel": "input[placeholder='Account']",
        "pass_sel": "input[placeholder='Password']",
        "btn_sel": "div.el-form-item__content button.el-button",
        "status_sel": "td.el-table_1_column_4.plant-list-cell.el-table__cell div.plant-status-column",
        "online_texto": "Normal",
    },
]
# =============================================


def get_db_connection():
    return mysql.connector.connect(
        unix_socket="/var/run/mysqld/mysqld.sock",
        user=os.getenv("DB_USER", "solar_user"),
        password=os.getenv("DB_PASS"),
        database=os.getenv("DB_NAME", "solar_monitor"),
    )


def obter_status_anterior(nome_usina: str) -> str:
    """Busca o último status salvo para a usina (ou None)."""
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT status
        FROM usinas_status
        WHERE nome_usina = %s
        """,
        (nome_usina,),
    )
    row = cur.fetchone()
    cur.close()
    conn.close()
    return row[0] if row else None


def salvar_status(nome_usina: str, status: str):
    """Insere ou atualiza status da usina na tabela usinas_status."""
    conn = get_db_connection()
    cur = conn.cursor()
    agora = datetime.now()

    cur.execute(
        """
        INSERT INTO usinas_status (nome_usina, status, updated_at)
        VALUES (%s, %s, %s)
        ON DUPLICATE KEY UPDATE
            status = VALUES(status),
            updated_at = VALUES(updated_at)
        """,
        (nome_usina, status, agora),
    )

    conn.commit()
    cur.close()
    conn.close()


GROWATT_API_BASE = "https://openapi.growatt.com/v1"


def get_growatt_headers(cfg: dict):
    token_env = cfg.get("token_env")
    if not token_env:
        raise RuntimeError(f"token_env não definido para {cfg['nome']}")
    token = os.getenv(token_env)
    if not token:
        raise RuntimeError(f"Variável {token_env} não encontrada no .env")
    return {"token": token}


def checar_usina_growatt_api(cfg: dict) -> str:
    nome = cfg["nome"]
    plant_id = cfg["plant_id"]
    limite_kw = cfg.get("limite_kw_online", 0.1)

    limite_minutos_offline = 10
    limite_minutos_erro = 240

    try:
        url = f"{GROWATT_API_BASE}/plant/data"
        params = {"plant_id": plant_id}
        resp = requests.get(
            url,
            headers=get_growatt_headers(cfg),
            params=params,
            timeout=15,
        )

        try:
            resp.raise_for_status()
        except HTTPError as http_err:
            status_code = resp.status_code
            msg = f"[{nome}] HTTP ERRO API Growatt ({status_code}): {http_err}"
            logger.error(msg)
            if 500 <= status_code < 600:
                msg2 = f"[{nome}] API 5xx, tentando fallback via Selenium..."
                logger.warning(msg2)
                try:
                    return checar_usina(cfg)  # fallback Selenium (se configurado)
                except Exception as e2:
                    msg3 = f"[{nome}] Fallback Selenium também falhou: {e2}"
                    logger.error(msg3)
                    status_antigo = obter_status_anterior(nome)
                    return status_antigo or "ERRO"
            return "ERRO"

        payload = resp.json()
        if payload.get("error_code") != 0:
            err = payload.get("error_msg")
            msg = f"[{nome}] ERRO API: {err}"
            logger.error(msg)
            if err == "error_frequently_access":
                msg2 = f"[{nome}] Rate limit na API, tentando fallback via Selenium..."
                logger.warning(msg2)
                try:
                    return checar_usina(cfg)
                except Exception as e2:
                    msg3 = f"[{nome}] Fallback Selenium também falhou: {e2}"
                    logger.error(msg3)
                    status_antigo = obter_status_anterior(nome)
                    return status_antigo or "ERRO"
            return "ERRO"

        data = payload.get("data", {}) or {}
        current_power = float(data.get("current_power", 0) or 0)
        last_update_raw = (data.get("last_update_time") or "").strip()

        msg = (
            f"[{nome}] current_power = {current_power} kW, "
            f"last_update_time = {last_update_raw}"
        )
        logger.info(msg)

        minutos_diferenca = None
        if last_update_raw:
            try:
                dt_local = datetime.strptime(last_update_raw, "%Y-%m-%d %H:%M:%S")
                dt_local = dt_local.replace(tzinfo=timezone(timedelta(hours=-3)))
                agora_local = datetime.now(timezone(timedelta(hours=-3)))
                minutos_diferenca = (agora_local - dt_local).total_seconds() / 60.0
            except Exception as e:
                msg = f"[{nome}] ERRO ao parsear last_update_time: {e}"
                logger.error(msg)
                minutos_diferenca = None

        if (
            minutos_diferenca is not None
            and minutos_diferenca <= limite_minutos_offline
        ):
            return "ONLINE"

        if current_power > limite_kw:
            return "ONLINE"

        if (
            minutos_diferenca is not None
            and limite_minutos_offline < minutos_diferenca <= limite_minutos_erro
        ):
            return "OFFLINE"

        if minutos_diferenca is not None and minutos_diferenca > limite_minutos_erro:
            return "ERRO"

        status_antigo = obter_status_anterior(nome)
        msg = f"[{nome}] Sem info confiável, mantendo status anterior: {status_antigo}"
        logger.warning(msg)
        return status_antigo or "ERRO"

    except Exception as e:
        msg = f"[{nome}] ERRO API Growatt: {e}"
        logger.error(msg)
        try:
            msg2 = f"[{nome}] Tentando Selenium como último recurso..."
            logger.warning(msg2)
            return checar_usina(cfg)
        except Exception as e2:
            msg3 = f"[{nome}] Selenium também falhou: {e2}"
            logger.error(msg3)
            return "ERRO"


def enviar_whatsapp_alerta(
    nome_usina: str, status_novo: str, status_antigo: str = None, responsavel: str = ""
):
    base_url = os.getenv("EVOLUTION_BASE_URL", "http://10.254.2.210:5080")
    instance = os.getenv("EVOLUTION_INSTANCE", "Solar")
    api_key = os.getenv("EVOLUTION_API_KEY", "F0R$@tl1")
    numero = os.getenv("WHATSAPP_NUMBER_ALERTA", "5585981699862")

    url = f"{base_url}/message/sendText/{instance}"

    texto = (
        "ALERTA MONITORAMENTO SOLAR\n\n"
        f"Usina: {nome_usina}\n"
        f"Status atual: {status_novo}\n"
        f"Responsável técnico: {responsavel or 'não cadastrado'}\n"
        f"Data/hora: {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}"
    )

    payload = {
        "number": numero,
        "text": texto,
        "options": {
            "delay": 1200,
            "presence": "composing",
            "linkPreview": False,
        },
    }

    headers = {
        "apikey": api_key,
        "Content-Type": "application/json",
    }

    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=15)
        msg = f"[WHATSAPP] HTTP {resp.status_code} - {resp.text}"
        logger.info(msg)
    except Exception as e:
        msg = f"[WHATSAPP] Erro ao enviar alerta: {e}"
        logger.error(msg)


def criar_driver():
    options = Options()
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1920,1080")
    options.add_argument("--remote-debugging-port=9222")

    options.binary_location = "/usr/bin/google-chrome"

    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=options)
    return driver


def checar_usina(cfg: dict) -> str:
    """Faz login em uma usina e detecta se está ONLINE ou OFFLINE."""
    driver = criar_driver()
    status_final = "ERRO"

    nome = cfg["nome"]
    debug_dir = os.path.join(os.path.dirname(__file__), "..", "debug")
    os.makedirs(debug_dir, exist_ok=True)

    try:
        msg = f"[{nome}] 1. Acessando URL: {cfg['url_login']}"
        logger.info(msg)
        driver.get(cfg["url_login"])

        import time

        msg = f"[{nome}] 1.5. Aguardando SPA carregar..."
        logger.info(msg)
        time.sleep(8)

        try:
            msg = f"[{nome}] 1.6. Fechando banner cookies..."
            logger.info(msg)
            cookie_disagree = driver.find_element(
                By.XPATH, "//button[contains(., 'I disagree')]"
            )
            cookie_disagree.click()
            time.sleep(2)
            msg = f"[{nome}] 1.7. Cookies fechados"
            logger.info(msg)
        except Exception:
            msg = f"[{nome}] 1.7. Sem banner cookies"
            logger.info(msg)

        driver.save_screenshot(f"{debug_dir}/{nome}_01_inicial.png")

        wait = WebDriverWait(driver, 30)

        msg = f"[{nome}] 2. Procurando campo usuário: {cfg['user_sel']}"
        logger.info(msg)
        el_user = wait.until(
            EC.presence_of_element_located((By.CSS_SELECTOR, cfg["user_sel"]))
        )
        el_user.clear()
        el_user.send_keys(os.getenv(cfg["usuario_env"]))
        driver.save_screenshot(f"{debug_dir}/{nome}_02_usuario_preenchido.png")

        msg = f"[{nome}] 3. Procurando campo senha: {cfg['pass_sel']}"
        logger.info(msg)
        el_pass = driver.find_element(By.CSS_SELECTOR, cfg["pass_sel"])
        el_pass.clear()
        el_pass.send_keys(os.getenv(cfg["senha_env"]))
        driver.save_screenshot(f"{debug_dir}/{nome}_03_senha_preenchida.png")

        msg = f"[{nome}] 4. Procurando botão: {cfg['btn_sel']}"
        logger.info(msg)
        btn = driver.find_element(By.CSS_SELECTOR, cfg["btn_sel"])
        driver.execute_script("arguments[0].scrollIntoView(true);", btn)
        driver.save_screenshot(f"{debug_dir}/{nome}_04_antes_clicar.png")

        try:
            btn.click()
        except Exception:
            driver.execute_script("arguments[0].click();", btn)

        msg = f"[{nome}] 5. Login clicado, aguardando..."
        logger.info(msg)
        time.sleep(5)
        driver.save_screenshot(f"{debug_dir}/{nome}_05_apos_login.png")

        msg = f"[{nome}] 6. Procurando status: {cfg['status_sel']}"
        logger.info(msg)

        try:
            el_status = wait.until(
                EC.presence_of_element_located((By.CSS_SELECTOR, cfg["status_sel"]))
            )
        except TimeoutException:
            msg = (
                f"[{nome}] 6b. Não achei '{cfg['status_sel']}', "
                f"tentando XPath do texto..."
            )
            logger.warning(msg)
            el_status = wait.until(
                EC.presence_of_element_located(
                    (
                        By.XPATH,
                        "//td[contains(normalize-space(.), 'Connection Status')]//span/span",
                    )
                )
            )

        driver.save_screenshot(f"{debug_dir}/{nome}_06_status_encontrado.png")

        texto = (el_status.text or "").strip().lower()
        msg = f"[{nome}] 7. Texto lido: '{texto}'"
        logger.info(msg)

        if cfg["online_texto"].lower() in texto:
            status_final = "ONLINE"
        else:
            status_final = "OFFLINE"

    except Exception as e:
        msg = f"[{nome}] ERRO DETALHADO: {type(e).__name__}: {str(e)}"
        logger.error(msg)
        driver.save_screenshot(f"{debug_dir}/{nome}_99_erro.png")

        with open(f"{debug_dir}/{nome}_erro.html", "w", encoding="utf-8") as f:
            f.write(driver.page_source)

        status_final = "ERRO"
    finally:
        driver.quit()

    return status_final


def checar_usina_cookies(cfg: dict) -> str:
    """Usina que usa cookies (sem login)."""
    import pickle, json as json_mod, time

    driver = criar_driver()
    status_final = "ERRO"
    nome = cfg["nome"]

    cookie_path = os.path.join(os.path.dirname(__file__), "..", cfg["cookie_file"])

    try:
        msg = f"[{nome}] 1. Carregando cookies..."
        logger.info(msg)

        if not os.path.exists(cookie_path):
            msg = f"[{nome}] ERRO: {cookie_path} não encontrado!"
            logger.error(msg)
            return "ERRO"

        driver.get(cfg["url_dashboard"])
        time.sleep(2)

        if cfg["cookie_file"].endswith(".pkl"):
            with open(cookie_path, "rb") as f:
                cookies = pickle.load(f)
        else:
            with open(cookie_path, "r", encoding="utf-8") as f:
                cookies = json_mod.load(f)

        for cookie in cookies:
            try:
                c = cookie.copy()
                c.pop("sameSite", None)
                driver.add_cookie(c)
            except Exception:
                pass

        msg = f"[{nome}] 2. Cookies carregados, acessando dashboard..."
        logger.info(msg)
        driver.refresh()
        time.sleep(8)

        msg = f"[{nome}] 3. Procurando status: {cfg['status_sel']}"
        logger.info(msg)
        el_status = driver.find_element(By.CSS_SELECTOR, cfg["status_sel"])
        texto = (el_status.text or "").strip().lower()
        msg = f"[{nome}] 4. Texto lido: '{texto}'"
        logger.info(msg)

        if cfg["online_texto"].lower() in texto:
            status_final = "ONLINE"
        elif "offline" in texto or "desligado" in texto:
            status_final = "OFFLINE"
        else:
            status_final = "ERRO"

    except Exception as e:
        msg = f"[{nome}] ERRO: {e}"
        logger.error(msg)
        status_final = "ERRO"
    finally:
        driver.quit()

    return status_final


def verificar_expiracao_cookies(cookie_file: str, dias_aviso: int = 5) -> dict:
    """
    Verifica se cookies estão próximos de expirar.
    Retorna: {"expira_em_dias": X, "precisa_renovar": True/False}
    """
    import pickle

    cookie_path = os.path.join(os.path.dirname(__file__), "..", cookie_file)

    if not os.path.exists(cookie_path):
        return {
            "expira_em_dias": 0,
            "precisa_renovar": True,
            "erro": "Arquivo não encontrado",
        }

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
                            "expira_em_dias": dias_restantes,
                            "expira_em": exp_date.strftime("%d/%m/%Y %H:%M"),
                            "precisa_renovar": dias_restantes <= dias_aviso,
                        }
                except Exception:
                    continue

        return {
            "expira_em_dias": -1,
            "precisa_renovar": False,
            "erro": "Sem JWT nos cookies",
        }

    except Exception as e:
        return {"expira_em_dias": 0, "precisa_renovar": True, "erro": str(e)}


def main():
    logger.info("=== Iniciando coleta de status das usinas ===")

    cookies_verificados = set()

    for cfg in USINAS:
        if cfg.get("usa_cookies") and cfg["cookie_file"] not in cookies_verificados:
            cookies_verificados.add(cfg["cookie_file"])
            info = verificar_expiracao_cookies(cfg["cookie_file"])

            if info.get("precisa_renovar"):
                dias = info.get("expira_em_dias", 0)
                if dias > 0:
                    msg = (
                        f"AVISO: Cookies de {cfg['nome']} expiram em {dias} dias "
                        f"({info.get('expira_em')}). Renove antes para evitar falhas!"
                    )
                else:
                    msg = f"URGENTE: Cookies de {cfg['nome']} expiraram ou estão inválidos!"
                logger.warning(msg)

    for cfg in USINAS:
        nome = cfg["nome"]
        responsavel = cfg.get("responsavel", "")
        logger.info(f"-> Checando {nome} ...")

        if cfg.get("tipo") == "growatt_api":
            status_novo = checar_usina_growatt_api(cfg)
        elif cfg.get("usa_cookies"):
            status_novo = checar_usina_cookies(cfg)
        else:
            status_novo = checar_usina(cfg)

        status_antigo = obter_status_anterior(nome)
        salvar_status(nome, status_novo)
        logger.info(f"{nome}: {status_novo} (antes: {status_antigo})")

        if status_novo in ("OFFLINE", "ERRO") and status_novo != status_antigo:
            msg = (
                f"[ALERTA] {nome} em estado crítico "
                f"({status_antigo} -> {status_novo}). Enviando WhatsApp..."
            )
            logger.warning(msg)
            enviar_whatsapp_alerta(nome, status_novo, status_antigo, responsavel)


if __name__ == "__main__":
    main()
