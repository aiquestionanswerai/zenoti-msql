from playwright.sync_api import sync_playwright
import time
import random
import re
import os
from dotenv import load_dotenv

# Load environment variables from .env file
dotenv_path = os.path.join(os.path.dirname(__file__), ".env")
load_dotenv(dotenv_path)

USERNAME = os.getenv("MINER_USER")
PASSWORD = os.getenv("MINER_PASSWORD")

if not USERNAME or not PASSWORD:
    raise ValueError("MINER_USER and MINER_PASSWORD must be set in the .env file.")


# Prompt the operator for the date range before starting
START_DATE = input("Please enter the Start Date (YYYY-MM-DD): ")
END_DATE = input("Please enter the End Date (YYYY-MM-DD): ")

with sync_playwright() as p:
    # Pass the argument to start the browser maximized
    browser = p.chromium.launch(headless=False, args=["--start-maximized"])
    
    # Set no_viewport=True to let the browser window size control the layout
    # I also recommend adding a user_agent to fix the "browser no longer supported" error shown in your screenshot
    context = browser.new_context(
        no_viewport=True,
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
    )
    page = context.new_page()

    # Open login page
    print("Navigating to login page...")
    page.goto("https://ids-az.cu.zenoti.com/Account/Login?ReturnUrl=%2Fconnect%2Fauthorize%2Fcallback%3Fclient_id%3D2360e9af-16d1-11ec-bbe9-0adc2855f3fb%26redirect_uri%3Dhttps%253A%252F%252Fevolvemedspa.zenoti.com%252Fsso%252Fredirect_callback.aspx%253Fids_error%253D%2526ids_relate_state%253D%2526ids_reply_url%253D%2526ids_machine_auth_only%253Dfalse%2526ids_machine_auth_id%253D98b075ab-9f5c-486d-981f-26765d164eaf%26response_type%3Dcode%26scope%3Dapi%2520openid%26state%3Db93d6986b1904fc3b96d398f2a850b6e%26code_challenge%3Dw0ctIVHEOLCiR8J-RffYQFoldHJcFFhEgzkJv1AO49g%26code_challenge_method%3DS256%26acr_values%3Dtenant%253Aevolvemedspa%26response_mode%3Dquery%26display_banner%3DTrue%26enable_machine_authentication%3Dtrue%26machine_auth_only%3DFalse%26use_ids_machine_auth%3DTrue%26machine_auth_id%3D98b075ab-9f5c-486d-981f-26765d164eaf%26machine_auth_key%26banner_message%3DAMRS12a%2520%252F%25202026.5.25.859%26ids_error_message%26is_chat_enabled%3DTrue%26intercom_app_id%3Dmv4uo5xy%26zenoti_req_id%3D$S2D%2523cLbqySxGjKOVkkpJ2ELMVTLnwfNAQNA38iw%252FPu89MfOHCnDznCwKSLA44qb2mZcm%252F3CKJn3J%26req_dt%3D1780408350")
    time.sleep(random.uniform(0.5, 3.5))
    page.wait_for_selector('#Username', state='visible')
    print("Login page loaded successfully.")

    # Login
    page.locator('#Username').fill(USERNAME)
    time.sleep(random.uniform(0.5, 1.5))
    print("Username entered.")
    
    page.locator('#Password').fill(PASSWORD)
    time.sleep(random.uniform(0.5, 1.5))
    print("Password entered.")
    time.sleep(random.uniform(2.0, 3.0))
    # Wait for the login button to be enabled before clicking.
    # This handles the delay caused by the CAPTCHA check.
    # The .click() action automatically waits for the button to be enabled.
    login_button = page.locator('#btnLogin')
    print("Waiting for login button to become enabled...")
    # print(">>> Please solve the CAPTCHA on the screen to enable the login button. <<<")
    # Set timeout to 0 to wait indefinitely for the CAPTCHA to be solved.
    # Playwright will wait until the button is enabled and then click it.
    login_button.click(timeout=0)
    print("Login button clicked. Waiting for dashboard...")
    time.sleep(random.uniform(2.0, 3.0))

    try:
        # Wait for the reports menu to be visible. This is more reliable than networkidle.
        # state='visible' ensures the element is ready for interaction and not blocked by overlays.
        page.locator('#menuLinkreports').wait_for(state='visible', timeout=60000)
        print("Dashboard loaded successfully.")
    except Exception as e:
        # If it fails, capture a screenshot to see what blocked the loading
        # (e.g. login error, center selection required, or a popup)
        print(f"Error: Dashboard menu not found. Current URL: {page.url}")
        page.screenshot(path="dashboard_load_error.png")
        print("Saved 'dashboard_load_error.png' for debugging.")
        raise e

    # Navigate to Reports
    page.locator('#menuLinkreports').click()
    time.sleep(random.uniform(1.0, 2.0))
    print("Navigated to Reports section.")

    # Click on Appointments and wait for the new tab to open
    with context.expect_page() as new_page_info:
        page.locator('span.report-name:has-text("Appointments")').click()
    
    time.sleep(random.uniform(1.0, 2.0))
    report_page = new_page_info.value
    report_page.wait_for_load_state("domcontentloaded")
    print("Appointments report page loaded successfully.")
    # Click the datepicker to open the range selection menu
    report_page.locator('#elm_dates').click()
    time.sleep(random.uniform(0.5, 1.0))

    # Select 'Custom Range' or 'Custom' from the menu
    report_page.locator('li:has-text("Custom Range"), li:has-text("Custom")').click()
    time.sleep(random.uniform(0.5, 1.0))

    # Helper to select date from the visual calendar
    def select_calendar_date(target_page, date_str, calendar_side):
        year, month, day = date_str.split('-')
        # Month in HTML value is 0-indexed (Jan=0, Feb=1...)
        month_val = str(int(month) - 1)
        day_val = str(int(day))
        
        # Select Year and Month
        target_page.locator(f'.drp-calendar.{calendar_side} .yearselect').select_option(year)
        time.sleep(random.uniform(0.2, 0.5))
        target_page.locator(f'.drp-calendar.{calendar_side} .monthselect').select_option(month_val)
        time.sleep(random.uniform(0.2, 0.5))
        
        # Click the day cell (ensuring it's not a day from the previous/next month)
        # We use a regex to match the exact day number so "1" doesn't match "11" or "21"
        day_selector = f'.drp-calendar.{calendar_side} td.available:not(.off):has-text("{day_val}")'
        target_page.locator(day_selector).filter(has_text=re.compile(f"^{day_val}$")).first.click()
        time.sleep(random.uniform(0.2, 0.5))

    # Select Start Date (usually left calendar)
    select_calendar_date(report_page, START_DATE, "left")
    
    # Select End Date (usually right calendar, but can be left if start/end are on same month)
    # Note: If Zenoti only shows one calendar at a time, use "left" for both.
    # Most versions of this picker use "right" for the second calendar.
    try:
        select_calendar_date(report_page, END_DATE, "right")
    except:
        select_calendar_date(report_page, END_DATE, "left")

    # Click Apply on the date picker
    report_page.locator('button.applyBtn').click()
    time.sleep(random.uniform(1.0, 2.0))
    print("Date range selected successfully.")

    # Click the Refresh button to load data for the selected range
    report_page.locator('#btnRefresh').click()
    # Wait for the report to refresh. Using networkidle is a good option here.
    report_page.wait_for_load_state("networkidle", timeout=60000)

    # Click the Export dropdown icon
    report_page.locator('#dropdownMenuLink').click()
    time.sleep(random.uniform(0.5, 1.0))

    # Click 'CSV' and wait for the download to start (using the element ID you provided)
    with report_page.expect_download() as download_info:
        report_page.locator('#export_csv').click()

    download = download_info.value
    # Use a descriptive filename with a .csv extension to ensure the OS recognizes it correctly.
    filename = f"appointments_report_{START_DATE}_to_{END_DATE}.csv"
    download.save_as(filename)
    print(f"Report downloaded successfully: {filename}")

    time.sleep(random.uniform(2.0, 4.0))
    browser.close()