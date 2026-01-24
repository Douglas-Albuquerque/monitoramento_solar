#!/usr/bin/env python3
"""
Extrai cookies de uma sessão autenticada do Solarman
Rode APÓS fazer login manual no navegador
"""
import pickle
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
import time

options = Options()
options.add_argument('--no-sandbox')
options.add_argument('--disable-dev-shm-usage')

driver = webdriver.Chrome(options=options)

print("Abrindo Solarman...")
driver.get("https://home.solarmanpv.com/login")

print("\n=== FAÇA LOGIN MANUAL NO NAVEGADOR ===")
print("1. Selecione o país")
print("2. Faça login com email/senha")
print("3. Resolva o captcha")
print("4. Aguarde entrar no dashboard")
print("\nQuando estiver LOGADO, digite 's' e ENTER aqui:")

input()

# Salvar cookies
cookies = driver.get_cookies()
with open("cookies_solarman.pkl", "wb") as f:
    pickle.dump(cookies, f)

print(f"\n✅ {len(cookies)} cookies salvos em cookies_solarman.pkl")
driver.quit()
