# main.py → Versão FINAL para GitHub Actions + Windows (2025)
import os
import sys
import time
import base64
from datetime import datetime, timedelta

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException

from supabase import create_client

# Config via variáveis de ambiente (seguras no Actions)
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_ANON_KEY")
TABLE_NAME = "tiktok_sessions"
TIMEOUT_MINUTES = 5

if len(sys.argv) != 2:
    print("Erro: session_id não fornecido")
    sys.exit(1)

row_id = sys.argv[1]
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

# === Configuração do Chrome (funciona no Actions e local) ===
options = webdriver.ChromeOptions()

if os.getenv("GITHUB_ACTIONS") == "true":
    print("Modo GitHub Actions → headless")
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1920,1080")
else:
    print("Modo local → janela visível")
    options.add_argument("--start-maximized")

options.add_argument("--disable-blink-features=AutomationControlled")
options.add_experimental_option("excludeSwitches", ["enable-automation"])
options.add_experimental_option("useAutomationExtension", False)

driver = webdriver.Chrome(options=options)
driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => false})")

deadline = datetime.utcnow() + timedelta(minutes=TIMEOUT_MINUTES)

def update(data: dict):
    data["id"] = row_id
    data["updated_at"] = datetime.utcnow().isoformat()
    if data.get("status") in ["expired", "error"]:
        data["closed_at"] = datetime.utcnow().isoformat()
    supabase.table(TABLE_NAME).upsert(data, on_conflict="id").execute()
    print(f"Status → {data.get('status')}")

try:
    driver.get("https://www.tiktok.com/login/qrcode")
    print("Carregando página de login QR...")

    canvas = WebDriverWait(driver, 30).until(
        EC.presence_of_element_located((By.CSS_SELECTOR, "[data-e2e='qr-code'] canvas"))
    )

    # Envia QR inicial
    qr_b64 = driver.execute_script("return arguments[0].toDataURL('image/png');", canvas).split(",")[1]
    update({
        "qrcode_base64": qr_b64,
        "status": "waiting_scan",
        "qrcode_expires_at": deadline.isoformat()
    })

    while True:
        now = datetime.utcnow()

        # Timeout 5 minutos
        if now >= deadline:
            update({"status": "expired"})
            print("Sessão expirada (5 min)")
            break

        url = driver.current_url.lower()

        # Logado com sucesso
        if "login" not in url:
            cookies = driver.get_cookies()
            update({
                "status": "logged",
                "cookies": cookies,
                "logged_at": now.isoformat(),
                "closed_at": None
            })
            print(f"LOGADO! {len(cookies)} cookies salvos no Supabase")
            break

        # QR escaneado
        try:
            el = driver.find_element(By.CSS_SELECTOR, "p.tiktok-awot1l-PCodeTip.eot7zvz17")
            if el.is_displayed() and "scanned" in el.text.lower():
                update({"status": "scanned"})
                print("QR escaneado → confirme no app")
        except:
            pass

        # QR mudou ou expirou → renova
        try:
            new_b64 = driver.execute_script("return arguments[0].toDataURL('image/png');", driver.find_element(By.CSS_SELECTOR, "[data-e2e='qr-code'] canvas")).split(",")[1]
            if new_b64 != qr_b64:
                qr_b64 = new_b64
                update({
                    "qrcode_base64": qr_b64,
                    "status": "waiting_scan"
                })
                print("Novo QR detectado e enviado")
        except:
            if "login" in url:
                print("QR sumiu → refresh")
                driver.refresh()
                canvas = WebDriverWait(driver, 20).until(EC.presence_of_element_located((By.CSS_SELECTOR, "[data-e2e='qr-code'] canvas")))
                qr_b64 = driver.execute_script("return arguments[0].toDataURL('image/png');", canvas).split(",")[1]
                update({"qrcode_base64": qr_b64, "status": "waiting_scan"})

        time.sleep(1.3)

except Exception as e:
    update({"status": "error", "error_message": str(e)})
    print(f"Erro crítico: {e}")
finally:
    driver.quit()
    print("Script finalizado.")