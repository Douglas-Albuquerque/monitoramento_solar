import os
import json
import pickle

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

json_path = os.path.join(BASE_DIR, "cookies_ufv_atlanta.json")
pkl_path = os.path.join(BASE_DIR, "cookies_ufv_atlanta.pkl")

with open(json_path, "r", encoding="utf-8") as f:
    cookies = json.load(f)

print(f"Lidos {len(cookies)} cookies do JSON")

selenium_cookies = []
for c in cookies:
    cd = {
        "domain": c["domain"],
        "path": c.get("path", "/"),
        "name": c["name"],
        "value": c["value"],
        "secure": c.get("secure", False),
    }
    if "expirationDate" in c:
        try:
            cd["expiry"] = int(c["expirationDate"])
        except Exception:
            pass
    selenium_cookies.append(cd)

print(f"Convertidos {len(selenium_cookies)} cookies para formato Selenium")

with open(pkl_path, "wb") as f:
    pickle.dump(selenium_cookies, f)

print(f"Salvo em: {pkl_path}")
