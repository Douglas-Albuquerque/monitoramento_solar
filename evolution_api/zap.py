import requests
import json

# CONFIGURAÇÕES
base_url = "http://10.254.2.210:5080"
instance_name = "Solar"
api_key = "F0R$@tl1"
numero_destino = "5585981699862"

# ENDPOINT
url = f"{base_url}/message/sendText/{instance_name}"

# CABEÇALHOS
headers = {
    "apikey": api_key,
    "Content-Type": "application/json"
}

# CORPO DA REQUISIÇÃO CORRIGIDO (v2.3.3)
payload = {
    "number": numero_destino,
    "text": "🧪 TESTE AUTOMÁTICO - Evolution API v2.3.3 ✅\n\nPara: 5585981699862\nInstance: Solar\nStatus: OK\n\nScript Python corrigido e funcionando!",  # Campo 'text' na raiz!
    "options": {
        "delay": 1200,
        "presence": "composing",
        "linkPreview": True
    }
}

print(f"🚀 Enviando mensagem para {numero_destino}...")
print(f"📡 URL: {url}")
print("📋 Payload CORRIGIDO:")
print(json.dumps(payload, indent=2, ensure_ascii=False))

try:
    response = requests.post(url, headers=headers, json=payload, timeout=30)
    
    print(f"\n📊 Status Code: {response.status_code}")
    
    if response.status_code in [200, 201, 202]:
        print("✅ Mensagem enviada com sucesso!")
        print("📄 Response:")
        print(json.dumps(response.json(), indent=2, ensure_ascii=False))
    else:
        print(f"❌ Erro HTTP {response.status_code}")
        print("📄 Response de erro:")
        print(response.text)

except Exception as e:
    print(f"💥 Erro: {str(e)}")

print("\n🎉 Script finalizado!")
