
from playwright.sync_api import sync_playwright

url = "https://careers.ibm.com/en_US/careers/JobDetail?jobId=123797&source=WEB_Search_NA"

with sync_playwright() as p:

    browser = p.chromium.launch(headless=False)
    page = browser.new_page()

    respuesta = page.goto(
        url,
        wait_until="domcontentloaded",
        timeout=30000
    )

    print("Estado HTTP:", respuesta.status if respuesta else None)

    titulo = page.locator("h2.banner__text__title")

    try:
        titulo.first.wait_for(timeout=10000)
        print("Puesto:", titulo.first.inner_text())
    except Exception:
        print("No se pudo localizar el título de la oferta")

    browser.close()
