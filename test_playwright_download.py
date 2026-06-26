from playwright.sync_api import sync_playwright
import time

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    context = browser.new_context()
    page = context.new_page()
    try:
        url = "https://storage.vortexscans.org//upload/series/became-the-patron-of-villains/UPuotvpAKk/001.webp"
        print(f"Playwright requesting {url}...")
        start = time.time()
        # Set referrer and headers in the request
        response = page.request.get(url, headers={
            "Referer": "https://vortexscans.org/"
        })
        body = response.body()
        print(f"Status: {response.status}, Size: {len(body)}, Time: {time.time() - start:.2f}s")
    except Exception as e:
        print(f"Error: {e}")
    finally:
        browser.close()
