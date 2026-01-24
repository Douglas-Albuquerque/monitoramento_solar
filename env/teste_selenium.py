from selenium import webdriver
from selenium.webdriver.chrome.options import Options

print("Testando Chrome...")
options = Options()
options.add_argument('--headless=new')
options.add_argument('--no-sandbox')
options.add_argument('--disable-dev-shm-usage')
options.add_argument('--disable-gpu')

driver = webdriver.Chrome(options=options)
driver.get('https://www.google.com')
print('✅ Selenium FINAL OK!')
print('Título:', driver.title)
print('Chrome version:', driver.capabilities['browserVersion'])
print('ChromeDriver version:', driver.capabilities['chrome']['chromedriverVersion'])
driver.quit()
