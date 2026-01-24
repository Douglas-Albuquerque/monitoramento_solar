# ☀️ Solar Dashboard - Monitoramento de Usinas Fotovoltaicas

Dashboard web em tempo real para monitoramento de múltiplas usinas solares fotovoltaicas com coleta automatizada via Selenium.

![Dashboard Preview](docs/screenshot-dashboard.png)

## 📋 Funcionalidades

- ✅ Monitoramento de **4 usinas solares** em tempo real
- ✅ Interface web responsiva (desktop, tablet e mobile)
- ✅ Coleta automatizada via **Selenium** (headless Chrome)
- ✅ Suporte a múltiplos portais:
  - Growatt Server (`server.growatt.com`)
  - iSolarCloud (`web3.isolarcloud.com.hk`)
  - Solarman (`home.solarmanpv.com`) - com autenticação por cookies
- ✅ Atualização automática a cada **5 minutos** (cron)
- ✅ Dashboard auto-refresh a cada **2 minutos**
- ✅ Alertas de expiração de cookies (contagem regressiva)
- ✅ Logs detalhados + screenshots de debug
- ✅ Cards coloridos por status (Verde/Vermelho/Cinza)

---

## 🛠️ Tecnologias

### Backend
- **Python 3.10+**
- **Flask** - Framework web
- **Selenium 4.25** - Automação de browser
- **MySQL-Connector-Python** - Integração com banco de dados
- **python-dotenv** - Gerenciamento de variáveis de ambiente

### Frontend
- **HTML5 + CSS3**
- **Bootstrap 5.3** - Layout responsivo
- **Jinja2** - Template engine

### Infraestrutura
- **MariaDB** - Banco de dados
- **Google Chrome 144** + **ChromeDriver 144** - Browser headless
- **Cron** - Agendamento de tarefas
- **Ubuntu Server 22.04**

---

