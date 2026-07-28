"""
Arkansas Food Bank - Agency Express Scraper
Logs in, scrapes all pages of inventory AND the current pending order.
Saves to inventory.json and order.json
"""

import json
import time
import re
import os
from datetime import datetime, timezone, timedelta
from playwright.sync_api import sync_playwright

# Central Time (UTC-5 standard, UTC-6 daylight — use fixed offset or detect)
def now_central():
    """Return current datetime in US Central time."""
    import time as _time
    # Use UTC and offset by -5 or -6 depending on DST
    utc_now = datetime.now(timezone.utc)
    # Simple DST approximation: CDT (UTC-5) Mar-Nov, CST (UTC-6) Nov-Mar
    month = utc_now.month
    is_dst = 3 <= month <= 11
    offset = timedelta(hours=-5 if is_dst else -6)
    return utc_now.astimezone(timezone(offset))

# ── Credentials (set as environment variables or GitHub Actions secrets) ─────
USERNAME     = os.environ.get("AE_USERNAME", "")
PASSWORD     = os.environ.get("AE_PASSWORD", "")
PROGRAM_CODE = os.environ.get("AE_PROGRAM_CODE", "")

# ── Settings ─────────────────────────────────────────────────
LOGIN_URL      = "https://www.agencyexpress3.org/AgencyExpress30/NewLogin.aspx"
SHOPPING_URL   = "https://www.agencyexpress3.org/AgencyExpress30/Shopper/ShoppingList.aspx"
OUTPUT_FILE       = "inventory.json"
ORDER_OUTPUT_FILE = "order.json"
ORDER_MGMT_URL    = "https://www.agencyexpress3.org/AgencyExpress30/Shopper/OrderManagement.aspx"
GRID_ID           = "ctl00$contentPH$gvShoppingList"

# Columns to capture (must match AE3 header text)
KEEP_COLUMNS = [
    "Available Qty.",
    "Item No.",
    "Description",
    "UOM",
    "Pack Size",
    "Feature Type",
    "Gross Weight",
]

item_code_re = re.compile(r'^[A-Z]\d{2}-\d{3,4}[A-Z]?$')


def scrape():
    print(f"[{now_central().strftime('%Y-%m-%d %H:%M:%S')}] Starting scrape...")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        # ── 1. Log in ────────────────────────────────────────
        print("  Logging in...")
        page.goto(LOGIN_URL, wait_until="networkidle")
        page.fill('input[id*="tbUserName"], input[type="text"]:first-of-type', USERNAME)
        page.fill('input[type="password"]', PASSWORD)
        page.fill('#ctl00_contentPH_Login1_tbProgramCode', PROGRAM_CODE)
        page.click('input[type="submit"]')
        page.wait_for_load_state("networkidle")
        print("  Logged in.")

        # ── 2. Close Activity Status Alert if present ─────────
        try:
            close_btn = page.wait_for_selector("input[value='Close']", timeout=4000)
            close_btn.click()
            page.wait_for_load_state("networkidle")
            print("  Alert closed.")
        except Exception:
            print("  No alert, continuing...")

        # ── 3. Go to Shopping List ────────────────────────────
        print("  Navigating to Shopping List...")
        page.goto(SHOPPING_URL, wait_until="networkidle")
        time.sleep(1)

        # ── 4. Find total number of pages ────────────────────
        page_links = page.query_selector_all(f"a[href*=\"'{GRID_ID}'\"]")
        page_numbers = set()
        for link in page_links:
            txt = link.inner_text().strip()
            if txt.isdigit():
                page_numbers.add(int(txt))

        total_pages = max(page_numbers) if page_numbers else 1
        print(f"  Found {total_pages} page(s) of inventory.")

        # ── 5. Scrape page 1 then click through remaining ────
        all_items = []

        for page_num in range(1, total_pages + 1):
            if page_num > 1:
                print(f"  Navigating to page {page_num}...")
                # Trigger ASP.NET postback to change page
                page.evaluate(f"__doPostBack('{GRID_ID}', 'Page${page_num}')")
                page.wait_for_load_state("networkidle")
                time.sleep(1)

            print(f"  Scraping page {page_num}...")
            items = scrape_table(page)
            print(f"    Got {len(items)} items.")
            all_items.extend(items)

        # ── 6. Scrape the current order (same session) ────────
        order_data = scrape_order(page, script_dir=os.path.dirname(os.path.abspath(__file__)))

        browser.close()

    # ── 7. Compare with previous run to tag new items ────────
    script_dir   = os.path.dirname(os.path.abspath(__file__))
    prev_path    = os.path.join(script_dir, "previous_items.json")
    now_iso      = now_central().isoformat()
    cutoff_hours = 24

    # Load previous new-item timestamps if they exist
    try:
        with open(prev_path, "r") as f:
            prev_data = json.load(f)
        prev_codes    = set(prev_data.get("item_codes", []))
        prev_new_tags = prev_data.get("new_tags", {})
    except Exception:
        prev_codes    = set()
        prev_new_tags = {}

    # Build current item codes set
    current_codes = set(item.get("Item No.", "") for item in all_items)

    # Carry forward new tags that are less than 24 hours old
    from datetime import timezone
    now_dt = now_central()
    active_new_tags = {}
    for code, ts in prev_new_tags.items():
        try:
            tag_dt = datetime.fromisoformat(ts)
            hours_old = (now_dt - tag_dt).total_seconds() / 3600
            if hours_old < cutoff_hours:
                active_new_tags[code] = ts
        except Exception:
            pass

    # Tag any item codes not seen in previous run
    newly_added = current_codes - prev_codes
    for code in newly_added:
        if code and code not in active_new_tags:
            active_new_tags[code] = now_iso
            print(f"  New item detected: {code}")

    # Apply new_since timestamp to each item
    for item in all_items:
        code = item.get("Item No.", "")
        if code in active_new_tags:
            item["new_since"] = active_new_tags[code]

    # Save previous items tracker (stays local, never pushed to GitHub)
    with open(prev_path, "w") as f:
        json.dump({"item_codes": list(current_codes), "new_tags": active_new_tags}, f, indent=2)

    # ── 8. Save results ───────────────────────────────────────
    now = now_central()
    output = {
        "updated_at": now.strftime("%B %d, %Y at %I:%M %p"),
        "updated_at_iso": now.isoformat(),
        "item_count": len(all_items),
        "items": all_items,
    }

    out_path = os.path.join(script_dir, OUTPUT_FILE)

    with open(out_path, "w") as f:
        json.dump(output, f, indent=2)

    print(f"  Done! {len(all_items)} items saved to {out_path}")
    return output


def scrape_table(page):
    """Extract inventory rows from the current page of the shopping list."""
    items = []

    # Find the grid by looking for the table containing real item codes
    tables = page.query_selector_all("table")
    target_table = None

    for table in tables:
        rows = table.query_selector_all("tr")
        for row in rows[1:5]:
            cells = row.query_selector_all("td")
            for cell in cells:
                if item_code_re.match(cell.inner_text().strip()):
                    target_table = table
                    break
            if target_table:
                break
        if target_table:
            break

    if not target_table:
        print("  WARNING: Could not find inventory table on this page.")
        return items

    # Map column names to indices
    headers = [th.inner_text().strip() for th in target_table.query_selector_all("th")]
    col_indices = {}
    for keep in KEEP_COLUMNS:
        for i, h in enumerate(headers):
            if keep.lower().rstrip(".") in h.lower():
                col_indices[keep] = i
                break

    # Extract rows
    rows = target_table.query_selector_all("tr")
    for row in rows[1:]:
        cells = row.query_selector_all("td")
        if not cells:
            continue

        item = {}
        for col_name, idx in col_indices.items():
            if idx < len(cells):
                item[col_name] = cells[idx].inner_text().strip()

        # Only keep rows with a valid item code
        if item_code_re.match(item.get("Item No.", "")):
            items.append(item)

    return items


def scrape_order(page, script_dir):
    """
    Navigate to Order Management, find the pending order, load its print
    preview, and save order.json.  Runs inside the existing logged-in session.
    """
    print("  Navigating to Order Management...")
    page.goto(ORDER_MGMT_URL, wait_until="networkidle")
    time.sleep(1)

    # ── Find the PO number from the print/view icon link ──────
    po_number = None
    try:
        po_link = page.locator("a[href*='PrintPreview.aspx?PONumber=']").first
        po_href = po_link.get_attribute("href", timeout=5000)
        po_number = po_href.split("PONumber=")[-1].strip()
        print(f"  Found pending order: {po_number}")
    except Exception:
        print("  WARNING: No pending order found — order.json will be empty.")

    if not po_number:
        output = {
            "scraped_at": now_central().isoformat(),
            "po_number": None,
            "appointment": {},
            "summary": {},
            "items": [],
            "note": "No pending order found at time of scrape.",
        }
        out_path = os.path.join(script_dir, ORDER_OUTPUT_FILE)
        with open(out_path, "w") as f:
            json.dump(output, f, indent=2)
        return output

    # ── Load print preview ────────────────────────────────────
    base = "https://www.agencyexpress3.org/AgencyExpress30"
    print_url = f"{base}/Shopper/PrintPreview.aspx?PONumber={po_number}"
    print(f"  Loading print preview: {print_url}")
    page.goto(print_url, wait_until="networkidle")
    time.sleep(1)

    # ── Appointment block ─────────────────────────────────────
    appointment = {"reference_number": po_number}
    try:
        # Pickup row: label cell + value cell side by side
        pickup_row = page.locator("td:has-text('Pickup')").first
        row_text   = pickup_row.locator("xpath=..").inner_text()
        lines = [l.strip() for l in row_text.splitlines() if l.strip()]
        # Usually: ['Pickup/Delivery', 'Date/Time', 'Pickup', '06/17/2026 @ 08:30 AM']
        for i, line in enumerate(lines):
            if re.match(r'\d{2}/\d{2}/\d{4}', line):
                appointment["pickup_date"] = line
                break
    except Exception:
        pass

    # ── Summary block ─────────────────────────────────────────
    summary = {}
    summary_labels = [
        "Total Due", "Total Line Items",
        "Gross Weight", "Total Cube Size",
        "Estimated Delivery Fee",
    ]
    for label in summary_labels:
        try:
            el  = page.locator(f"text={label}").first
            val = el.locator("xpath=following::*[contains(@style,'color') or self::td][1]").inner_text().strip()
            summary[label] = val
        except Exception:
            pass

    # ── Cart items ────────────────────────────────────────────
    items = scrape_order_table(page)
    print(f"  Order has {len(items)} line items.")

    output = {
        "scraped_at":   now_central().isoformat(),
        "po_number":    po_number,
        "appointment":  appointment,
        "summary":      summary,
        "items":        items,
    }

    out_path = os.path.join(script_dir, ORDER_OUTPUT_FILE)
    with open(out_path, "w") as f:
        json.dump(output, f, indent=2)
    print(f"  Order saved to {out_path}")
    return output


def scrape_order_table(page):
    """Extract cart rows from the PrintPreview page, skipping Unit Price."""
    items = []
    SKIP = {"unit price"}

    tables = page.query_selector_all("table")
    cart_table = None
    for table in tables:
        headers = [th.inner_text().strip() for th in table.query_selector_all("th")]
        joined  = " ".join(h.lower() for h in headers)
        if "description" in joined and ("order" in joined or "qty" in joined):
            cart_table = table
            break

    if not cart_table:
        print("  WARNING: Could not find cart table on print preview page.")
        return items

    headers = [th.inner_text().strip().replace("\r\n", " ").replace("\n", " ")
               for th in cart_table.query_selector_all("th")]
    print(f"  Order columns: {headers}")

    # Build index→name map, skipping Unit Price
    col_map = {
        i: h for i, h in enumerate(headers)
        if h.lower().replace("\r\n", " ").replace("\n", " ") not in SKIP
    }

    rows = cart_table.query_selector_all("tr")
    for row in rows[1:]:
        cells = row.query_selector_all("td")
        if not cells:
            continue
        item = {}
        for idx, col_name in col_map.items():
            if idx < len(cells):
                item[col_name] = cells[idx].inner_text().strip()
        if item.get("Description") or item.get("Item No."):
            items.append(item)

    return items



if __name__ == '__main__':
    scrape()
