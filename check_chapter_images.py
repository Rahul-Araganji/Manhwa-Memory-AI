from playwright.sync_api import sync_playwright
import time

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page()
    try:
        url = "https://vortexscans.org/series/became-the-patron-of-villains/chapter-2"
        print(f"Navigating to {url}...")
        page.goto(url, wait_until="domcontentloaded")
        print("Waiting 3 seconds...")
        time.sleep(3)
        
        # Scrape images before scrolling
        img_srcs_before = page.evaluate("""() => {
            return Array.from(document.querySelectorAll('img')).map(img => img.src);
        }""")
        print(f"Found {len(img_srcs_before)} images before scrolling.")
        
        # Scroll to bottom slowly to trigger lazy loading
        print("Scrolling to the bottom...")
        for i in range(10):
            page.evaluate(f"window.scrollTo(0, document.body.scrollHeight * {i/10});")
            time.sleep(0.5)
        page.evaluate("window.scrollTo(0, document.body.scrollHeight);")
        time.sleep(2)
        
        # Scrape images after scrolling
        img_srcs_after = page.evaluate("""() => {
            return Array.from(document.querySelectorAll('img')).map(img => img.src);
        }""")
        print(f"Found {len(img_srcs_after)} images after scrolling.")
        
        # Count how many have "/upload/series/"
        valid_before = [s for s in img_srcs_before if s and "/upload/series/" in s]
        valid_after = [s for s in img_srcs_after if s and "/upload/series/" in s]
        print(f"Manga panels before scrolling: {len(valid_before)}")
        print(f"Manga panels after scrolling: {len(valid_after)}")
        
        # Print a few URLs to see
        print("\nFirst 5 panels after scrolling:")
        for v in valid_after[:5]:
            print(v)
            
    except Exception as e:
        print(f"Error: {e}")
    finally:
        browser.close()
