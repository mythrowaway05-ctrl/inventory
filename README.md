# Arkansas Food Bank — Inventory Website
## Setup Instructions

You have two files:
- `scraper.py` — pulls inventory from Agency Express, saves to `inventory.json`
- `index.html` — the website that reads `inventory.json` and displays it

---

## Step 1: Install Python dependencies

Open a terminal and run:

```bash
pip install playwright
playwright install chromium
```

---

## Step 2: Set your credentials

**Option A — Environment variables (recommended):**

On Mac/Linux, add these to your `~/.zshrc` or `~/.bash_profile`:
```bash
export AE_USERNAME="your_username"
export AE_PASSWORD="your_password"
export AE_PROGRAM_CODE="your_program_code"
```
Then run `source ~/.zshrc` to reload.

On Windows, search "Environment Variables" in the Start menu and add them there.

**Option B — Edit the script directly (only if this stays on your private machine):**

Open `scraper.py` and fill in lines 15–17:
```python
USERNAME     = "your_username"
PASSWORD     = "your_password"
PROGRAM_CODE = "your_program_code"
```

---

## Step 3: Run the scraper manually (first test)

```bash
python scraper.py
```

This will open a headless browser, log in, and save `inventory.json` next to the script.
You should see output like:
```
[2024-01-15 10:30:00] Starting scrape...
  Logging in...
  Logged in.
  Navigating to inventory...
  Scraping page 1...
  Scraping page 2...
  Done! 247 items saved to /path/to/inventory.json
```

If it can't find the inventory table, see the Troubleshooting section below.

---

## Step 4: View the website locally

Open `index.html` in your browser. It will read `inventory.json` from the same folder.

**Important:** Open it through a local server, not by double-clicking the file.
The easiest way:
```bash
cd /path/to/your/foodbank/folder
python -m http.server 8000
```
Then visit `http://localhost:8000` in your browser.

---

## Step 5: Schedule automatic scraping

### Mac / Linux (cron):
Run `crontab -e` and add this line to run every 30 minutes:
```
*/30 * * * * /usr/bin/python3 /full/path/to/scraper.py >> /full/path/to/scraper.log 2>&1
```

### Windows (Task Scheduler):
1. Open Task Scheduler
2. Create Basic Task → name it "Food Bank Scraper"
3. Trigger: Daily, repeat every 30 minutes
4. Action: Start a program → `python.exe`
5. Arguments: `C:\full\path\to\scraper.py`

---

## Step 6: Host the website

Put `index.html` and `inventory.json` in the same folder on any web host.
Free options:
- **GitHub Pages** — push both files to a repo, enable Pages in Settings
- **Netlify Drop** — drag the folder to netlify.com/drop
- **Any shared hosting** — upload via FTP

The scraper writes `inventory.json` locally. If you host online, you'll need to
copy/upload `inventory.json` after each scrape, OR run the scraper on the same
machine as the server.

---

## Troubleshooting

**"Could not find inventory table"**
Agency Express may use a slightly different layout for your food bank.
Run the scraper with `headless=False` to watch the browser:
```python
browser = p.chromium.launch(headless=False)
```
Watch what page it lands on after login, and update the selectors in `scraper.py` accordingly.

**Login fails**
- Double-check your username, password, and program code
- Some AE3 installs have a slightly different login form — inspect the page source
  and update the `page.fill(...)` selectors in the `scrape()` function

**Pagination not working**
If your inventory spans multiple pages and only the first page appears,
inspect the "Next" button on the AE3 site and update the `next_btn` selector.
