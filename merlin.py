import re
import sys
import time
import random
import asyncio
import json
from bs4 import BeautifulSoup
import requests
import aiohttp
from playwright.async_api import async_playwright


def _make_event_loop():
    """Создаёт event loop: ProactorEventLoop на Windows, обычный на macOS/Linux."""
    if sys.platform == 'win32':
        return asyncio.ProactorEventLoop()
    return asyncio.new_event_loop()

# Local proxy/VPN for DoneDeal requests (browser uses the same)
DONEDEAL_PROXY = ""

print("OK")

# List of User-Agents for iPhone (as in donedeal_bot)
MOBILE_USER_AGENTS = [
    # iOS Safari (current — iOS 26, Safari 26)
    "Mozilla/5.0 (iPhone; CPU iPhone OS 26_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/26.0 Mobile/15E148 Safari/604.1",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 25_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/25.5 Mobile/15E148 Safari/604.1",
    "Mozilla/5.0 (iPad; CPU OS 26_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/26.0 Mobile/15E148 Safari/604.1",
]

def get_random_user_agent():
    """Returns random User-Agent for iPhone"""
    return random.choice(MOBILE_USER_AGENTS)

# Variable to track time of last request
_last_request_time = 0
MIN_REQUEST_DELAY = 1.0  # Minimum delay between requests (seconds)

def _wait_between_requests():
    """Adds pause between requests to avoid triggering rate limiting"""
    global _last_request_time
    elapsed = time.time() - _last_request_time
    if elapsed < MIN_REQUEST_DELAY:
        sleep_time = MIN_REQUEST_DELAY - elapsed + random.uniform(0.1, 0.3)
        time.sleep(sleep_time)
    _last_request_time = time.time()

def get_url():
    """Gets URL of first available auction"""
    print("working")
    
    # Use requests instead of Selenium
    user_agent = get_random_user_agent()
    headers = {
        'User-Agent': user_agent,
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.9',
        'Accept-Encoding': 'gzip, deflate, br',
        'Connection': 'keep-alive',
        'Upgrade-Insecure-Requests': '1',
    }
    
    try:
        response = requests.get('https://www.merlin.ie/', headers=headers, timeout=30)
        response.raise_for_status()
        
        # Look for auction links on main page
        soup = BeautifulSoup(response.text, "html.parser")
        auction_links = soup.find_all('a', href=re.compile(r'/auction/\d+'))
        
        if auction_links:
            # Take first available auction
            first_auction_href = auction_links[0].get('href')
            first_auction_id = first_auction_href.split('/')[-1]
            # Return auction page URL directly
            url = f'https://www.merlin.ie/auction/{first_auction_id}'
            print(f"Found auction ID: {first_auction_id}")
            return url
        else:
            # Fallback - try to find any auction
            return 'https://www.merlin.ie/auction/68'  # Can use last known
    
    except Exception as e:
        print(f"Error getting URL: {e}")
        # Fallback - return last known auction
        return 'https://www.merlin.ie/auction/68'

def get_car_link(url):
    """Gets car links from catalog page (deprecated method)"""
    user_agent = get_random_user_agent()
    headers = {
        'User-Agent': user_agent,
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.9',
        'Accept-Encoding': 'gzip, deflate, br',
        'Connection': 'keep-alive',
        'Upgrade-Insecure-Requests': '1',
    }
    
    response = requests.get(url, headers=headers, timeout=30)
    response.raise_for_status()
    
    soup = BeautifulSoup(response.text, "html.parser")
    # Look for car links by new pattern /vehicle/{id}
    vehicle_links = soup.find_all('a', href=re.compile(r'/vehicle/[a-z0-9]+'))

    links = []
    for link in vehicle_links:
        href = link.get('href', '')
        if href:
            full_url = 'https://www.merlin.ie' + href if href.startswith('/') else href
            if full_url not in links:
                links.append(full_url)

    return links


async def get_cars_async(auction_url, user_id, bot):
    """
    Collects car data from merlin.ie asynchronously, then gets prices from DoneDeal.
    """
    # Test message to verify bot is working
    try:
        print(f"\n[TEST] Sending test message to chat {user_id}...")
        bot.send_message(user_id, "🚀 Starting auction parsing...")
        print(f"[TEST] Test message sent successfully")
    except Exception as e:
        print(f"[TEST] Error sending test message: {e}")
        import traceback
        traceback.print_exc()
    
    # Get auction ID from URL
    auction_id = auction_url.split('/')[-1] if '/' in auction_url else auction_url
    
    # STEP 1: Collect all car cards from all pages (asynchronously)
    print("\n" + "="*60)
    print("STEP 1: Collecting all car cards from all pages (asynchronously)")
    print("="*60)

    def _requests_get(url):
        """Синхронный GET через requests — работает надёжно на Windows."""
        h = {
            'User-Agent': get_random_user_agent(),
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.9',
            'Connection': 'keep-alive',
        }
        resp = requests.get(url, headers=h, timeout=30, verify=False)
        return resp.status_code, resp.text

    async def async_get(url):
        """Async-обёртка над requests.get через thread-pool."""
        return await asyncio.to_thread(_requests_get, url)

    if True:  # structurally replaces "async with session"
        # First, determine total number of pages
        print("Determining number of pages...")
        first_page_url = f'https://www.merlin.ie/auction/{auction_id}'

        try:
            status, html = await async_get(first_page_url)
            if status != 200:
                print(f"Error loading first page: status {status}")
                return

            soup = BeautifulSoup(html, "html.parser")

            # Determine max page number from pagination
            pagination = soup.find('ul', class_='pagination') or soup.find('nav', class_='pagination')
            max_page = 1

            if pagination:
                page_links = pagination.find_all('a')
                for page_link in page_links:
                    href = page_link.get('href', '')
                    text = page_link.get_text().strip()

                    # Look for page number in href
                    page_match = re.search(r'page=(\d+)', href)
                    if page_match:
                        page_num = int(page_match.group(1))
                        if page_num > max_page:
                            max_page = page_num

                    # Look for page number in text
                    if text.isdigit():
                        page_num = int(text)
                        if page_num > max_page:
                            max_page = page_num

            print(f"Found pages: {max_page}")

            # Function to load and parse one page
            async def load_and_parse_page(page_num, semaphore):
                """Loads and parses one page"""
                async with semaphore:
                    try:
                        await asyncio.sleep(random.uniform(0.5, 1.5) * page_num)

                        if page_num == 1:
                            page_url = f'https://www.merlin.ie/auction/{auction_id}'
                        else:
                            page_url = f'https://www.merlin.ie/auction/{auction_id}?page={page_num}'

                        status, html = await async_get(page_url)
                        if status != 200:
                            print(f"  ✗ Page {page_num}: error status {status}")
                            return []

                        soup = BeautifulSoup(html, "html.parser")

                        # Find all car cards
                        product_cards = soup.find_all('div', class_='product-card')
                        print(f"  ✓ Page {page_num}: found {len(product_cards)} cards")

                        page_cars = []

                        for card in product_cards:
                            car_data = {}

                            vehicle_link = card.find('a', href=re.compile(r'/vehicle/'))
                            if vehicle_link:
                                href = vehicle_link.get('href', '')
                                car_data['lot_url'] = 'https://www.merlin.ie' + href if href.startswith('/') else href
                            else:
                                continue

                            img = card.find('img', class_='card-img-top')
                            if img:
                                img_src = img.get('src', '')
                                car_data['img_url'] = img_src if img_src else '/images/comingsoon.jpg'
                            else:
                                car_data['img_url'] = '/images/comingsoon.jpg'

                            lot_elem = card.find('div', class_='card-lot')
                            if lot_elem:
                                lot_link = lot_elem.find('a')
                                if lot_link:
                                    lot_text = ' '.join(lot_link.get_text().strip().split())
                                    if lot_text:
                                        car_data['lot_number'] = lot_text

                            reg_elem = card.find('div', class_='card-reg')
                            if reg_elem:
                                car_data['registration'] = reg_elem.get_text().strip()

                            make_elem = card.find('h2', class_='card-title')
                            if make_elem:
                                car_data['make'] = make_elem.get_text().strip()
                            else:
                                continue

                            card_title_wrap = card.find('div', class_='card-title-wrap')
                            if card_title_wrap:
                                paragraphs = card_title_wrap.find_all('p')
                                if len(paragraphs) >= 1:
                                    car_data['model'] = paragraphs[0].get_text().strip()
                                if len(paragraphs) >= 2:
                                    car_data['variant'] = paragraphs[1].get_text().strip()

                            time_elem = card.find('li', class_='icon-item-time')
                            if time_elem:
                                date_text = time_elem.get_text().strip()
                                date_match = re.search(r'(\d{2}/\d{2}/\d{4})', date_text)
                                car_data['date_auctions'] = date_match.group(1).replace('/', '.') if date_match else date_text

                            details_ul = card.find('ul', class_='details-list')
                            if details_ul:
                                for item in details_ul.find_all('li', class_='detail-item'):
                                    span = item.find('span')
                                    strong = item.find('strong')
                                    if span and strong:
                                        label = span.get_text().strip()
                                        value = strong.get_text().strip()
                                        if 'Miles' in label or 'Mileage' in label:
                                            car_data['odom'] = value
                                        elif 'Fuel Type' in label or 'Fuel' in label:
                                            car_data['fuel'] = value
                                        elif 'Transmission' in label:
                                            car_data['transmission'] = value
                                        elif 'Colour' in label:
                                            car_data['colour'] = value

                            car_data.setdefault('odom', 'Unknown')
                            car_data.setdefault('transmission', 'Unknown')
                            car_data.setdefault('fuel', 'Unknown')
                            car_data.setdefault('model', 'Unknown')
                            car_data['nct'] = 'Unknown'
                            car_data['tax'] = 'Unknown'
                            car_data['owners'] = 'Unknown'
                            car_data['body'] = 'Unknown'
                            car_data['car_name'] = f"{car_data.get('make', '')} {car_data.get('model', '')}"
                            if car_data.get('variant'):
                                car_data['car_name'] += f" {car_data['variant']}"
                            car_data['year'] = None
                            car_data['cat_notes'] = []
                            car_data['autoguru'] = None
                            car_data['details'] = None

                            page_cars.append(car_data)

                        return page_cars

                    except Exception as e:
                        print(f"  ✗ Error loading page {page_num}: {e}")
                        return []

            # Load all pages in parallel
            print(f"\nLoading {max_page} pages in parallel...")
            page_semaphore = asyncio.Semaphore(5)

            tasks = [load_and_parse_page(page_num, page_semaphore) for page_num in range(1, max_page + 1)]
            results = await asyncio.gather(*tasks, return_exceptions=True)

            # Collect all cards from all pages
            all_cars_data = []
            for page_num, result in enumerate(results, 1):
                if isinstance(result, Exception):
                    print(f"  ✗ Page {page_num}: exception {result}")
                elif isinstance(result, list):
                    all_cars_data.extend(result)
                else:
                    print(f"  ⚠ Page {page_num}: unexpected result {type(result)}")
                
        except Exception as e:
            print(f"Error determining number of pages: {e}")
            import traceback
            traceback.print_exc()
            return
        
        print(f"\nTotal car cards collected: {len(all_cars_data)}")
        
        if not all_cars_data:
            print("No cars found for processing")
            return
        
        # STEP 2: Asynchronously get all details for all cars
        print("\n" + "="*60)
        print(f"STEP 2: Getting details for {len(all_cars_data)} cars (asynchronously)")
        print("="*60)
        
        merlin_semaphore = asyncio.Semaphore(5)  # Up to 5 concurrent requests
        
        detail_tasks = [
            get_additional_details_from_vehicle_page_async(None, car_data['lot_url'], merlin_semaphore)
            for car_data in all_cars_data
        ]
        details_list = await asyncio.gather(*detail_tasks)
        
        # Update car data with obtained details
        from datetime import datetime
        for idx, (car_data, details) in enumerate(zip(all_cars_data, details_list), 1):
            print(f"\n[Details {idx}] Car: {car_data.get('make', 'Unknown')} {car_data.get('model', 'Unknown')}")
            print(f"  Obtained from detail page:")
            print(f"    - Year: {details.get('year', 'N/A')}")
            print(f"    - NCT: {details.get('nct', 'N/A')}")
            print(f"    - TAX: {details.get('tax', 'N/A')}")
            print(f"    - Lot Number: {details.get('lot_number', 'N/A')}")
            print(f"    - Autoguru: {details.get('autoguru', 'N/A')}")
            print(f"    - Cat Notes: {len(details.get('cat_notes', []))} notes")
            print(f"    - Details: {details.get('details', 'N/A')}")
            # Update year
            if details.get('year'):
                car_data['year'] = details['year']
            elif 'year' not in car_data or not car_data.get('year'):
                car_data['year'] = str(datetime.now().year - 5)
            
            # Update NCT and TAX
            if details.get('nct'):
                car_data['nct'] = details['nct']
            elif car_data.get('nct') == 'Unknown':
                # If NCT not found, leave as is or set "-"
                car_data['nct'] = '-'
            
            if details.get('tax'):
                car_data['tax'] = details['tax']
            elif car_data.get('tax') == 'Unknown':
                # If TAX not found, leave as is or set "-"
                car_data['tax'] = '-'
            
            # Update lot number (if found on detail page)
            if details.get('lot_number'):
                car_data['lot_number'] = details['lot_number']
                print(f"  ✓ Lot Number updated from detail page: {car_data['lot_number']}")
            elif car_data.get('lot_number') == 'Lot TBC' or car_data.get('lot_number') == 'Lot: Unknown' or car_data.get('lot_number', '').startswith('Lot TBC'):
                # Try to extract lot number from cat_notes if present
                # Cat notes may contain numbers like "221D28064", "182D534", "151CE2843"
                if details.get('cat_notes'):
                    for note in details['cat_notes']:
                        note_str = str(note)
                        # Look for pattern like "221D28064" or "182D534" or "151CE2843"
                        # This is usually a reference number that could be a lot number
                        lot_match = re.search(r'(\d{2,3}[A-Z]{0,2}\d{3,})', note_str)
                        if lot_match:
                            lot_num = lot_match.group(1)
                            # Check that it's not too long (not a year or mileage)
                            if len(lot_num) <= 10:
                                car_data['lot_number'] = f"Lot: {lot_num}"
                                print(f"  ✓ Lot Number extracted from cat_notes: {car_data['lot_number']}")
                                break
                
                # If still not found, try to extract from registration or other places
                if car_data.get('lot_number', '').startswith('Lot TBC') or car_data.get('lot_number') == 'Lot: Unknown':
                    # Try to find in registration
                    if car_data.get('registration'):
                        reg = car_data['registration']
                        # Sometimes lot number can be in registration number
                        lot_match = re.search(r'(\d{2,3}[A-Z]{0,2}\d{3,})', reg)
                        if lot_match and len(lot_match.group(1)) <= 10:
                            lot_num = lot_match.group(1)
                            car_data['lot_number'] = f"Lot: {lot_num}"
                            print(f"  ✓ Lot Number extracted from registration: {car_data['lot_number']}")
                    
                    # If still not found, try to find in detail page URL
                    if car_data.get('lot_number', '').startswith('Lot TBC'):
                        # Sometimes number can be in URL or other metadata
                        # But usually on auction page it's really TBC until confirmed
                        print(f"  ⚠ Lot Number remains TBC (To Be Confirmed) - may not be confirmed yet")
            
            # Update Autoguru
            if details.get('autoguru'):
                car_data['autoguru'] = details['autoguru']
            
            # Update cat_notes (cleaned)
            if details.get('cat_notes'):
                car_data['cat_notes'] = details['cat_notes']
            
            # Update details
            if details.get('details'):
                car_data['details'] = details['details']
                print(f"  ✓ Details updated: {car_data['details']}")
            elif details.get('details') is None or details.get('details') == '':
                # If Details not found but Autoguru exists, add standard text
                if details.get('autoguru') or car_data.get('autoguru'):
                    car_data['details'] = "See Autoguru report"
                    print(f"  ✓ Details added automatically (Autoguru exists): {car_data['details']}")
            else:
                print(f"  ⚠ Details not found in details: {details.get('details', 'None')}")
            
            # Update car_name with year (uppercase)
            car_name_parts = [car_data['year']]
            if car_data.get('make'):
                car_name_parts.append(car_data['make'].upper())
            if car_data.get('model'):
                car_name_parts.append(car_data['model'].upper())
            if car_data.get('variant'):
                car_name_parts.append(car_data['variant'].upper())
            
            car_data['car_name'] = ' '.join(car_name_parts)
            
            # Form donedeal link
            car_data['donedal_link'] = get_donedeal_link(
                car_data['car_name'], 
                car_data.get('transmission', 'Manual'),
                car_data.get('fuel', 'Diesel')
            )
        
        print("Details obtained for all cars")
        
        # STEP 3: Get prices from DoneDeal and send to Telegram immediately
        print("\n" + "="*60)
        print(f"STEP 3: Getting prices and sending {len(all_cars_data)} cars to Telegram")
        print("="*60)
        print(f"[DEBUG] Starting price retrieval and sending for {len(all_cars_data)} cars")
        
        # Check that we have data to send
        if not all_cars_data:
            print("[ERROR] No data to send!")
            try:
                bot.send_message(user_id, "❌ Error: no data to send")
            except:
                pass
            return
        
        # Send message about start of processing
        try:
            bot.send_message(user_id, f"📊 Processing {len(all_cars_data)} cars...")
            print(f"[STEP 3] Initial message sent")
        except Exception as e:
            print(f"[STEP 3] Error sending initial message: {e}")
        
        for idx, car_data in enumerate(all_cars_data, 1):
            print(f"\n[{idx}/{len(all_cars_data)}] Processing: {car_data.get('car_name', 'Unknown')}")

            # Carzone valuation by registration
            reg = car_data.get('registration', '').strip()
            odom = car_data.get('odom', '')
            if reg:
                print(f"    Getting Carzone valuation for {reg}...")
                cz = await get_carzone_valuation(reg, odom)
                car_data['carzone'] = cz
                if cz:
                    print(f"    ✓ Carzone: Retail €{cz['retail_excellent']}/€{cz['retail_standard']}/€{cz['retail_poor']}")
                else:
                    print(f"    ✗ Carzone: no data")
            else:
                car_data['carzone'] = None
                print(f"    ⚠ No registration — Carzone skipped")

            # Get price from DoneDeal
            print(f"    Getting price from DoneDeal...")
            print(f"    DoneDeal URL: {car_data.get('donedal_link', 'N/A')}")
            avg, price_count = await get_avg(car_data['donedal_link'])

            if avg is not None:
                car_data['avg'] = avg
                car_data['total'] = price_count
                print(f"    ✓ Price obtained: AVG=€{int(avg)}, Count={price_count}")
            else:
                car_data['avg'] = None
                car_data['total'] = None
                print(f"    ✗ Price not found")
            
            # Send to Telegram immediately after getting price
            print(f"    Sending to Telegram...")
            try:
                send_car(car_data, user_id, bot)
                print(f"    ✓ Car sent to Telegram successfully")
            except Exception as e:
                print(f"    ✗ Error sending to Telegram: {e}")
                import traceback
                traceback.print_exc()
                # Try to send at least a text message about the error
                try:
                    bot.send_message(user_id, f"❌ Error sending car {idx} ({car_data.get('car_name', 'Unknown')}): {str(e)[:200]}")
                except:
                    pass
            
            # Small delay between processing cars
            await asyncio.sleep(0.5)
        
        print("\n" + "="*60)
        print(f"Processing completed! Processed cars: {len(all_cars_data)}")
        print("="*60)
        
        # Send final message
        try:
            bot.send_message(user_id, f"✅ Parsing completed! Processed cars: {len(all_cars_data)}")
            print(f"[FINAL] Final message sent successfully")
        except Exception as e:
            print(f"[FINAL] Error sending final message: {e}")
            import traceback
            traceback.print_exc()
    
    print("\n" + "="*60)
    print("Parsing completed!")
    print("="*60)

async def get_additional_details_from_vehicle_page_async(session, vehicle_url, semaphore):
    """Asynchronously gets additional details (year, NCT, TAX, autoguru, notes) from detail page"""
    async with semaphore:  # Limit concurrent requests
        try:
            # Delay between requests
            await asyncio.sleep(random.uniform(0.5, 1.5))

            def _fetch():
                h = {
                    'User-Agent': get_random_user_agent(),
                    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
                    'Accept-Language': 'en-US,en;q=0.9',
                    'Connection': 'keep-alive',
                }
                r = requests.get(vehicle_url, headers=h, timeout=30, verify=False)
                return r.status_code, r.text

            status, html = await asyncio.to_thread(_fetch)
            if status != 200:
                print(f"Error getting {vehicle_url}: status {status}")
                return {}

            soup = BeautifulSoup(html, "html.parser")

            # Save HTML for debugging (only for first few requests)
            import os
            debug_dir = "html_dumps"
            if not os.path.exists(debug_dir):
                os.makedirs(debug_dir)
            if len([f for f in os.listdir(debug_dir) if f.startswith('vehicle_detail_')]) < 3:
                filename = f"{debug_dir}/vehicle_detail_{vehicle_url.split('/')[-1]}.html"
                with open(filename, 'w', encoding='utf-8') as f:
                    f.write(html)
                print(f"  [DEBUG] Saved HTML: {filename}")

            details = {}

            # Look for year in car name
            h1 = soup.find('h1', class_='title-h1')
            if h1:
                car_name = h1.get_text().strip()
                year_match = re.search(r'\b(19|20)\d{2}\b', car_name)
                if year_match:
                    details['year'] = year_match.group(0)
                
            # Look for NCT and TAX in details
            details_ul = soup.find('ul', class_='details-list')
            if details_ul:
                detail_items = details_ul.find_all('li', class_='detail-item')
                print(f"  [DEBUG] Found {len(detail_items)} elements in details-list")
                for item in detail_items:
                    span = item.find('span')
                    strong = item.find('strong')
                    if span and strong:
                        label = span.get_text().strip()
                        value = strong.get_text().strip()
                        if 'NCT' in label.upper() or 'National Car Test' in label:
                            if value:
                                details['nct'] = value
                        elif 'TAX' in label.upper() or 'Tax Expiry' in label or 'Road Tax' in label:
                            if value:
                                details['tax'] = value
                        elif 'Registered' in label:
                            year_match = re.search(r'/(\d{4})', value)
                            if year_match and 'year' not in details:
                                details['year'] = year_match.group(1)

            if 'nct' not in details:
                nct_elem = soup.find(string=re.compile(r'NCT|National Car Test', re.I))
                if nct_elem:
                    parent = nct_elem.find_parent(['li', 'div', 'span'])
                    if parent:
                        nct_match = re.search(r'(\d{2}/\d{2}/\d{4})', parent.get_text())
                        if nct_match:
                            details['nct'] = nct_match.group(1)

            if 'tax' not in details:
                tax_elem = soup.find(string=re.compile(r'Tax Expiry|Road Tax', re.I))
                if tax_elem:
                    parent = tax_elem.find_parent(['li', 'div', 'span'])
                    if parent:
                        tax_match = re.search(r'(\d{2}/\d{2}/\d{4})', parent.get_text())
                        if tax_match:
                            details['tax'] = tax_match.group(1)

            autoguru_link = (
                soup.find('a', class_=re.compile('btn.*btn-outline-secondary.*btn-block', re.I), href=re.compile('motorvehicleinspectionreport', re.I))
                or soup.find('a', href=re.compile(r'motorvehicleinspectionreport.*\.pdf', re.I))
                or next((l for l in soup.find_all('a', string=re.compile('View PDF', re.I)) if 'pdf' in l.get('href','').lower()), None)
                or soup.find('a', href=re.compile('autoguru', re.I))
                or (soup.find_all('a', string=re.compile('autoguru', re.I)) or [None])[0]
            )
            if autoguru_link:
                href = autoguru_link.get('href', '') or autoguru_link.get('data-href', '')
                if href:
                    details['autoguru'] = ('https://www.merlin.ie' + href) if href.startswith('/') else href

            lot_number = None
            lot_elem = soup.find('div', class_='card-lot')
            if lot_elem:
                lot_link = lot_elem.find('a')
                if lot_link:
                    lot_text = ' '.join(lot_link.get_text().strip().split())
                    if lot_text:
                        lot_number = lot_text
            if not lot_number:
                lot_span = soup.find('span', class_='pill-item-lot')
                if lot_span:
                    lot_text = lot_span.get_text().strip()
                    m = re.search(r'Lot\s*:?\s*(\d+)', lot_text, re.I) or re.search(r'(\d+)', lot_text)
                    if m:
                        lot_number = f"Lot: {m.group(1)}"
            if not lot_number:
                for lot_text in soup.find_all(string=re.compile(r'Lot\s*:?\s*\d+', re.I)):
                    m = re.search(r'Lot\s*:?\s*(\d+)', lot_text, re.I)
                    if m:
                        lot_number = f"Lot: {m.group(1)}"
                        break
            if lot_number:
                details['lot_number'] = lot_number

            cat_notes = []
            seen_notes = set()
            dealer_info = soup.find('div', class_=re.compile(r'dealer|seller|vendor', re.I))
            if dealer_info:
                dealer_text = ' '.join(dealer_info.get_text().strip().split())
                if 5 < len(dealer_text) < 100 and dealer_text not in seen_notes:
                    cat_notes.append(dealer_text)
                    seen_notes.add(dealer_text)
            service_info = soup.find(string=re.compile(r'service\s*history|stamp|stamps', re.I))
            if service_info:
                parent = service_info.find_parent(['div', 'section', 'li'])
                if parent:
                    service_text = ' '.join(parent.get_text().strip().split())
                    stamp_match = re.search(r'(\d+)\s*stamp', service_text, re.I)
                    if stamp_match:
                        note = f"{stamp_match.group(1)} Stamp Service History"
                        if note not in seen_notes:
                            cat_notes.append(note)
                            seen_notes.add(note)
            if cat_notes:
                details['cat_notes'] = cat_notes

            details_text = None
            see_autoguru = soup.find(string=re.compile(r'See\s+Autoguru\s+report', re.I))
            if see_autoguru:
                details_text = see_autoguru.strip()
            if not details_text and details.get('autoguru'):
                details_text = "See Autoguru report"
            if details_text:
                details['details'] = details_text

            print(f"  [DEBUG] Extracted from {vehicle_url}:")
            print(f"    - NCT: {details.get('nct', 'N/A')}")
            print(f"    - TAX: {details.get('tax', 'N/A')}")
            print(f"    - Autoguru: {details.get('autoguru', 'N/A')}")
            print(f"    - Lot Number: {details.get('lot_number', 'N/A')}")
            print(f"    - Cat Notes count: {len(details.get('cat_notes', []))}")

            return details
        except Exception as e:
            print(f"Error getting additional details for {vehicle_url}: {e}")
            return {}

def get_additional_details_from_vehicle_page(vehicle_url):
    """Synchronous version for backward compatibility"""
    try:
        user_agent = get_random_user_agent()
        headers = {
            'User-Agent': user_agent,
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.9',
            'Accept-Encoding': 'gzip, deflate, br',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
        }
        
        response = requests.get(vehicle_url, headers=headers, timeout=30)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")
        
        details = {}
        
        # Look for year in car name
        h1 = soup.find('h1', class_='title-h1')
        if h1:
            car_name = h1.get_text().strip()
            # Extract year (first 4-digit number)
            year_match = re.search(r'\b(19|20)\d{2}\b', car_name)
            if year_match:
                details['year'] = year_match.group(0)
        
        # Look for NCT and TAX in details
        details_list = soup.find('ul', class_='details-list')
        if details_list:
            detail_items = details_list.find_all('li', class_='detail-item')
            for item in detail_items:
                span = item.find('span')
                strong = item.find('strong')
                
                if span and strong:
                    label = span.get_text().strip()
                    value = strong.get_text().strip()
                    
                    if 'NCT Expiry' in label or 'NCT' in label:
                        details['nct'] = value
                    elif 'Tax Expiry' in label or 'TAX' in label:
                        details['tax'] = value
                    elif 'Registered' in label:
                        # Extract year from registration date
                        year_match = re.search(r'/(\d{4})', value)
                        if year_match and 'year' not in details:
                            details['year'] = year_match.group(1)
        
        return details
    except Exception as e:
        print(f"Error getting additional details: {e}")
        return {}



def get_cars(url, user_id, bot):
    """Main function for getting and processing cars"""
    # Check if this is auction page URL or catalog
    if '/auction/' in url:
        # New approach: parse data from auction page asynchronously
        print("Using new approach: asynchronous parsing from auction page")
        
        # Start asynchronous processing
        # Check if event loop is already running
        try:
            # Try to get running event loop
            loop = asyncio.get_running_loop()
            # If event loop is already running, need to use different approach
            # Create new thread for execution
            import threading
            import queue
            result_queue = queue.Queue()
            
            def run_in_thread():
                new_loop = _make_event_loop()
                asyncio.set_event_loop(new_loop)
                try:
                    print("[THREAD] Starting asynchronous processing...")
                    new_loop.run_until_complete(get_cars_async(url, user_id, bot))
                    print("[THREAD] Asynchronous processing completed successfully")
                    result_queue.put(None)
                except Exception as e:
                    print(f"[THREAD] Error in asynchronous processing: {e}")
                    import traceback
                    traceback.print_exc()
                    result_queue.put(e)
                finally:
                    new_loop.close()
            
            thread = threading.Thread(target=run_in_thread, daemon=False)
            thread.start()
            thread.join()  # Wait for thread completion
            
            # Check if there was an error
            try:
                result = result_queue.get(timeout=1)
                if result:
                    print(f"Error in thread: {result}")
                    import traceback
                    traceback.print_exc()
                    raise result
            except queue.Empty:
                print("Warning: result from thread not received (thread may still be running)")
        except RuntimeError:
            loop = _make_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(get_cars_async(url, user_id, bot))
    else:
        # Old approach: through separate pages (for backward compatibility)
        print("Using old approach: through separate pages")

        def _run_old():
            new_loop = _make_event_loop()
            asyncio.set_event_loop(new_loop)
            try:
                new_loop.run_until_complete(_get_cars_old_async(url, user_id, bot))
            finally:
                new_loop.close()

        import threading
        t = threading.Thread(target=_run_old, daemon=False)
        t.start()
        t.join()


async def _get_cars_old_async(url, user_id, bot):
    """Async version of the old per-page scraping approach."""
    links = get_car_link(url)

    user_agent = get_random_user_agent()
    headers = {
        'User-Agent': user_agent,
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.9',
        'Accept-Encoding': 'gzip, deflate, br',
        'Connection': 'keep-alive',
        'Upgrade-Insecure-Requests': '1',
    }
        
    for link in links:
        data = {}
        _wait_between_requests()

        try:
            response = requests.get(link, headers=headers, timeout=30)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, "html.parser")
        except Exception as e:
            print(f"Error loading {link}: {e}")
            continue

        h1 = soup.find('h1', class_='title-h1')
        if h1:
            data['car_name'] = h1.get_text().strip()
        else:
            continue

        lot_span = soup.find('span', class_='pill-item-lot')
        if lot_span:
            lot_text = lot_span.get_text().strip()
            if lot_text and len(lot_text) > 3:
                data['lot_number'] = lot_text
            else:
                parent = lot_span.parent
                if parent:
                    parent_text = parent.get_text().strip()
                    lot_match = re.search(r'Lot\s*:?\s*\d+', parent_text, re.I)
                    data['lot_number'] = lot_match.group(0) if lot_match else (lot_text or 'Lot: Unknown')
                else:
                    data['lot_number'] = 'Lot: Unknown'
        else:
            data['lot_number'] = 'Lot: Unknown'

        time_span = soup.find('span', class_='pill-item-time')
        if time_span:
            date_text = time_span.get_text().strip()
            date_match = re.search(r'(\d{2}/\d{2}/\d{4})', date_text)
            data['date_auctions'] = date_match.group(1).replace('/', '.') if date_match else date_text
        else:
            data['date_auctions'] = 'Unknown'

        gallery_img = soup.find('div', class_='ug-slider-inner')
        if gallery_img:
            first_img = gallery_img.find('img')
            if first_img:
                data['img_url'] = first_img.get('src', '')
        if not data.get('img_url'):
            all_imgs = soup.find_all('img', src=re.compile(r'merlin-prod-data-s3-public|motorvehicle'))
            data['img_url'] = all_imgs[0].get('src', '') if all_imgs else '/images/comingsoon.jpg'

        data['lot_url'] = link

        details_list = soup.find('ul', class_='details-list')
        if details_list:
            for item in details_list.find_all('li', class_='detail-item'):
                span = item.find('span')
                strong = item.find('strong')
                if span and strong:
                    label = span.get_text().strip()
                    value = strong.get_text().strip()
                    if 'Odometer' in label:
                        data['odom'] = value
                    elif 'Transmission' in label:
                        data['transmission'] = value
                    elif 'Fuel' in label:
                        data['fuel'] = value
                    elif 'NCT Expiry' in label:
                        data['nct'] = value
                    elif 'Tax Expiry' in label:
                        data['tax'] = value
                    elif 'Former Keepers' in label:
                        data['owners'] = value
                    elif 'Body type' in label:
                        data['body'] = value

        for key in ('odom', 'transmission', 'fuel', 'nct', 'tax', 'owners', 'body'):
            data.setdefault(key, 'Unknown')

        cat_notes = []
        for section in soup.find_all('div', class_='content-section'):
            for p in section.find_all('p'):
                text = p.get_text().strip()
                if text and len(text) > 10 and text not in cat_notes:
                    cat_notes.append(text)
        data['cat_notes'] = cat_notes

        autoguru_link = soup.find('a', href=re.compile('autoguru', re.I))
        if autoguru_link:
            href = autoguru_link.get('href', '')
            if href:
                data['autoguru'] = 'https://www.merlin.ie' + href if href.startswith('/') else href

        data['donedal_link'] = get_donedeal_link(data['car_name'], data['transmission'], data['fuel'])
        print(f"DoneDeal Link: {data['donedal_link']}")

        reg = data.get('registration', '').strip()
        odom = data.get('odom', '')
        data['carzone'] = await get_carzone_valuation(reg, odom) if reg else None

        avg, price_count = await get_avg(data['donedal_link'])
        data['avg'] = avg
        data['total'] = price_count if avg is not None else None

        print(data)
        send_car(data, user_id, bot)

def send_car(i, user_id, bot):
    """Sends car information to Telegram"""
    print(f"\n[send_car] Starting to send car: {i.get('car_name', 'Unknown')}")
    print(f"[send_car] user_id: {user_id}, type: {type(user_id)}")
    print(f"[send_car] bot: {bot}, type: {type(bot)}")
    print(f"[send_car] img_url: {i.get('img_url', 'N/A')}")
    
    # Check that bot and user_id are valid
    if not bot:
        print(f"  ✗ [send_car] Error: bot is None")
        return
    if not user_id:
        print(f"  ✗ [send_car] Error: user_id is None")
        return
    
    try:
        img_url = i.get('img_url', '')
        if not img_url:
            print(f"  ⚠ img_url missing, using placeholder")
            img_url = '/images/comingsoon.jpg'
        
        if img_url.startswith('/images/comingsoon.jpg'):
            response = requests.get(f"https://www.merlin.ie{img_url}", timeout=30)
        else:
            response = requests.get(img_url, timeout=30)
        
        print(f"[send_car] Image loading status: {response.status_code}")
        
        if response.status_code == 200:
            # Format exactly as in user example
            # 1. Lot number (monospace format) - only if exists
            caption = ""
            lot_number = i.get('lot_number', '').strip()
            if lot_number:
                # Normalize the lot number format
                if not lot_number.startswith('Lot'):
                    if lot_number.upper() == 'TBC':
                        lot_number = 'Lot TBC'
                    else:
                        # Try to extract number from text
                        lot_match = re.search(r'(\d+)', lot_number)
                        if lot_match:
                            lot_number = f"Lot: {lot_match.group(1)}"
                        else:
                            lot_number = f"Lot {lot_number}"
                caption = f"<code>{lot_number}</code>\n"
            
            # 2. Car name (uppercase) with hidden link
            car_name = i.get('car_name', 'Unknown').strip().upper()
            lot_url = i.get('lot_url', '')
            if lot_url:
                caption += f"<a href='{lot_url}'>{car_name}</a>\n\n"
            else:
                caption += f"{car_name}\n\n"
            
            # 3. Transmission, Fuel, Odometer
            transmission = i.get('transmission', 'Unknown')
            fuel = i.get('fuel', 'Unknown')
            odom = i.get('odom', 'Unknown')
            caption += f"🕹️ {transmission}\n"
            caption += f"⛽️ {fuel}\n"
            caption += f"📟 {odom}\n"
            
            # 4. NCT and TAX
            nct = i.get('nct', '-')
            tax = i.get('tax', '-')
            # If value is 'Unknown', replace with '-'
            if nct == 'Unknown':
                nct = '-'
            if tax == 'Unknown':
                tax = '-'
            caption += f"<b>NCT:</b> {nct}\n"
            caption += f"<b>TAX:</b> {tax}\n\n"
            
            # 5. Autoguru, Notes and Details section
            has_autoguru = 'autoguru' in i and i['autoguru']
            has_notes = 'cat_notes' in i and i['cat_notes'] and len(i['cat_notes']) > 0
            has_details = 'details' in i and i.get('details')
            
            if has_autoguru or has_notes or has_details:
                # Autoguru link (if exists) - hidden under text
                if has_autoguru:
                    autoguru_url = i['autoguru']
                    caption += f"<a href='{autoguru_url}'>Autoguru</a>\n\n"
                
                # Notes (each note on separate line)
                if has_notes:
                    notes_parts = []
                    if isinstance(i['cat_notes'], list):
                        # Filter and clean notes
                        for note in i['cat_notes']:
                            if note and isinstance(note, str):
                                # Clean from extra spaces and line breaks
                                note_clean = ' '.join(note.split())
                                # Skip too long or empty notes
                                if 5 < len(note_clean) < 150:
                                    notes_parts.append(note_clean)
                    else:
                        note_clean = ' '.join(str(i['cat_notes']).split())
                        if 5 < len(note_clean) < 150:
                            notes_parts.append(note_clean)
                    
                    # Remove duplicates
                    notes_parts = list(dict.fromkeys(notes_parts))  # Preserves order
                    
                    if notes_parts:
                        caption += f"<b>Notes:</b> {notes_parts[0]}\n"
                        # Other notes on separate lines
                        for note in notes_parts[1:]:
                            caption += f"{note}\n"
                
                # Details (if exists)
                if has_details:
                    caption += f"<b>Details:</b> {i['details']}\n"
                
                caption += "\n"
            
            # 6. Carzone valuation (if exists)
            cz = i.get('carzone')
            if cz:
                caption += (
                    f"<b>Carzone (Retail):</b>\n"
                    f"<code>Excellent: €{cz['retail_excellent']}</code>\n"
                    f"<code>Good:      €{cz['retail_standard']}</code>\n"
                    f"<code>Fair:      €{cz['retail_poor']}</code>\n"
                )

            # 7. AVG price (if exists) - monospace format
            if i.get('avg') is not None and i.get('total') is not None:
                avg_price = int(i['avg'])
                total_count = i['total']
                caption += f"<code>AVG: €{avg_price} ({total_count})</code>\n"

            # 8. DoneDeal link (hidden under text)
            donedal_link = i.get('donedal_link', '')
            if donedal_link:
                caption += f"<a href='{donedal_link}'>DoneDeal</a>"

            # Check lot number in different formats for pinning message
            lot_num = lot_number.strip()
            if lot_num in ['Lot: 1', 'Lot 1', 'Lot:1', 'Lot TBC'] and '1' in lot_num:
                # Check if this is really the first lot
                lot_match = re.search(r'Lot\s*:?\s*1\b', lot_num, re.I)
                if lot_match:
                    to_pin = bot.send_message(user_id, f"{i.get('date_auctions', 'Unknown')}", parse_mode='HTML')
                    bot.pin_chat_message(user_id, message_id=to_pin.message_id)
            
            try:
                print(f"  [DEBUG] Sending photo to chat {user_id}")
                print(f"  [DEBUG] Image size: {len(response.content)} bytes")
                print(f"  [DEBUG] Caption length: {len(caption)} characters")
                print(f"  [DEBUG] Caption (first 200 characters): {caption[:200]}")
                
                # Check caption length (Telegram limit 1024 characters)
                if len(caption) > 1024:
                    print(f"  ⚠ Caption too long ({len(caption)} characters), truncating to 1024")
                    caption = caption[:1021] + "..."
                
                result = bot.send_photo(user_id, response.content, caption=caption, parse_mode='HTML')
                print(f"  ✓ Photo sent successfully, message_id: {result.message_id if result else 'None'}")
            except Exception as e:
                print(f"  ✗ Error sending photo: {e}")
                import traceback
                traceback.print_exc()
                # Try to send text only
                try:
                    bot.send_message(user_id, f"Error sending photo for {i.get('car_name', 'Unknown')}\n\n{caption}", parse_mode='HTML')
                except Exception as e2:
                    print(f"  ✗ Error sending text: {e2}")
        else:
            print(f"  ✗ Failed to load image, status: {response.status_code}")
            # Fix: user_id is a number, not a message object
            try:
                bot.send_message(user_id, 'Failed to load image.')
            except Exception as e:
                print(f"  ✗ Error sending error message: {e}")
    except Exception as e:
        print(f"  ✗ Critical error in send_car: {e}")
        import traceback
        traceback.print_exc()

def get_donedeal_link(car_name, trans, fuel):
    # Normalize name format (can be "2010 Mercedes-benz B150")
    parts = car_name.split(' ')
    if len(parts) < 3:
        # Fallback for incorrect format
        year = parts[0] if len(parts) > 0 else '2020'
        make = parts[1].upper().replace('-', '') if len(parts) > 1 else 'UNKNOWN'
        model = parts[2].upper() if len(parts) > 2 else 'UNKNOWN'
    else:
        year = parts[0]
        make_part = parts[1]
        make = make_part.upper()
        model = parts[2].upper() if len(parts) > 2 else ''

    base = 'https://www.donedeal.ie/cars'

    # Normalize transmission and fuel
    trans = trans.upper() if trans else 'Manual'
    fuel = fuel.upper() if fuel else 'Diesel'

    # Normalize complex fuel types for URL (take first part)
    if '/' in fuel:
        fuel = fuel.split('/')[0].strip()

    def _title(s):
        """Приводим к Title Case для URL DoneDeal: 'QASHQAI' -> 'Qashqai'"""
        return s.capitalize()

    # Mapping for special cases (for URL encoding)
    make_url_mapping = {
        'MERCEDES-BENZ': 'Mercedes-Benz',
        'MERCEDESBENZ': 'Mercedes-Benz',
        'LANDROVER': 'Land Rover',
        'VW': 'Volkswagen',
        'ALFA': 'Alfa Romeo',
    }
    make_clean = make_url_mapping.get(make, _title(make))
    model_clean = _title(model)
    # URL-encode spaces as %20
    make_url = make_clean.replace(' ', '%20')
    model_url = model_clean.replace(' ', '%20')
    
    # Extract additional information from name if needed
    variant = ''
    if len(parts) > 3:
        variant = ' '.join(parts[3:]).upper()

    pf = "price_from=300"

    # Build the DoneDeal link based on make and model
    if 'LANDROVER' in make or make == 'LANDROVER':
        if model == 'RANGEROVER':
            if variant and any(v in variant for v in ['VELAR', 'SPORT', 'EVOQUE']):
                variant_part = variant.split()[0] if variant.split() else ''
                return f"{base}/Land%20Rover/Range%20Rover%20{variant_part}/{year}?transmission={trans}&fuelType={fuel}&{pf}"
            else:
                return f"{base}/Land%20Rover/Range%20Rover/{year}?transmission={trans}&fuelType={fuel}&{pf}"

        elif model == 'DISCOVERY':
            if variant and 'SPORT' in variant:
                return f"{base}/Land%20Rover/Discovery%20Sport/{year}?transmission={trans}&fuelType={fuel}&{pf}"
            else:
                return f"{base}/Land%20Rover/Discovery/{year}?transmission={trans}&fuelType={fuel}&{pf}"

        else:
            return f"{base}/Land%20Rover/{model}/{year}?transmission={trans}&fuelType={fuel}&{pf}"

    elif make == 'CITROEN':
        if model == 'C4':
            if variant and 'GRAND PICASSO' in variant:
                return f"{base}?make=Citroen;model:C4%20GRAND%20PICASSO,Grand%20C4%20Picasso&transmission={trans}&fuelType={fuel}&year_from={year}&year_to={year}&{pf}"

            elif variant and any(v in variant for v in ['PICASSO', 'CACTUS']):
                variant_part = variant.split()[0] if variant.split() else ''
                return f"{base}/Citroen/{model}%20{variant_part}/{year}?transmission={trans}&fuelType={fuel}&{pf}"

            else:
                return f"{base}/Citroen/{model}/{year}?transmission={trans}&fuelType={fuel}&{pf}"
        elif model == 'C3':
            return f"{base}/Citroen/{model}/{year}?transmission={trans}&fuelType={fuel}&{pf}"
    
    # Additional logic for other makes/models...

    else:
        # Use make_url for correct URL encoding
        return f"{base}/{make_url}/{model}/{year}?transmission={trans}&fuelType={fuel}&{pf}"

async def get_avg_from_url(url):
    """
    Gets average price from DoneDeal - only for cars with EXACT match of
    transmission and fuel type. No fallbacks that relax these filters.
    If no matching ads found, returns None (no average price sent).
    """
    try:
        from urllib.parse import urlparse, parse_qs, urlencode

        parsed = urlparse(url)
        path_parts = [p for p in parsed.path.split('/') if p]

        if len(path_parts) < 3 or path_parts[0] != 'cars':
            print(f"Invalid URL format: {url}")
            return None, 0

        make = path_parts[1] if len(path_parts) > 1 else ''
        model = path_parts[2] if len(path_parts) > 2 else ''
        year = path_parts[3] if len(path_parts) > 3 else ''

        query_params = parse_qs(parsed.query)
        transmission = query_params.get('transmission', [''])[0]
        fuel_type = query_params.get('fuelType', [''])[0]

        if not transmission or not fuel_type:
            print(f"  Skipping: transmission and fuel type required for price match")
            return None, 0

        print(f"Parsing URL: make={make}, model={model}, year={year}, transmission={transmission}, fuel={fuel_type}")

        base = f"https://www.donedeal.ie/cars/{make}/{model}"

        def build_url(use_year=True, year_from=None, year_to=None):
            path = base
            if use_year and year and not year_from:
                path += f"/{year}"
            params = {"price_from": "300", "transmission": transmission, "fuelType": fuel_type}
            if year_from and year_to:
                params["year_from"] = str(year_from)
                params["year_to"] = str(year_to)
            return f"{path}?{urlencode(params)}"

        prices = await get_all_prices(build_url())

        if len(prices) <= 1 and year:
            try:
                year_int = int(year)
                print(f"  [YEAR±1] Only {len(prices)} result, expanding to {year_int-1}–{year_int+1}...")
                prices = await get_all_prices(
                    build_url(use_year=False, year_from=year_int-1, year_to=year_int+1)
                )
            except (ValueError, TypeError):
                pass

        if not prices:
            print(f"  No ads with matching transmission and fuel type")
            return None, 0

        clean_prices = remove_price_outliers(prices)

        if clean_prices:
            avg = int(sum(clean_prices) / len(clean_prices))
            print(f"  ✓ Average: €{avg} ({len(clean_prices)} ads, {len(prices) - len(clean_prices)} outliers removed)")
            return avg, len(clean_prices)

        print(f"  ✗ All {len(prices)} prices removed as outliers")
        return None, 0
        
    except Exception as e:
        print(f"Error parsing URL {url}: {e}")
        import traceback
        traceback.print_exc()
        return None, 0


def remove_price_outliers(prices):
    """
    Removes outlier prices using IQR method (same as donedeal_bot).
    Returns cleaned price list.
    """
    if not prices or len(prices) < 2:
        return prices
    
    try:
        sorted_prices = sorted(prices)
        n = len(sorted_prices)
        
        q1_idx = n // 4
        q3_idx = (3 * n) // 4
        q1 = sorted_prices[q1_idx]
        q3 = sorted_prices[q3_idx]
        iqr = q3 - q1
        
        lower = q1 - 1.5 * iqr
        upper = q3 + 1.5 * iqr
        
        cleaned = [p for p in sorted_prices if lower <= p <= upper]
        return cleaned if len(cleaned) >= 2 else prices
    except Exception:
        return prices


# ---------------------------------------------------------------------------
# Async Playwright singletons (one browser, two pages)
# ---------------------------------------------------------------------------

_PW = None           # async_playwright instance
_PW_BROWSER = None   # shared Chromium browser
_CZ_PAGE = None      # carzone.ie page
_DD_PAGE = None      # donedeal.ie page

_PW_CONTEXT_OPTS = dict(
    user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
    locale='en-US',
    extra_http_headers={
        'sec-ch-ua': '"Google Chrome";v="131", "Chromium";v="131", "Not_A Brand";v="24"',
        'sec-ch-ua-mobile': '?0',
        'sec-ch-ua-platform': '"Windows"',
    },
)


async def _reset_playwright():
    """Полный сброс всех Playwright-синглтонов (при краше браузера)."""
    global _PW, _PW_BROWSER, _CZ_PAGE, _DD_PAGE
    _CZ_PAGE = None
    _DD_PAGE = None
    try:
        if _PW_BROWSER:
            await _PW_BROWSER.close()
    except Exception:
        pass
    try:
        if _PW:
            await _PW.stop()
    except Exception:
        pass
    _PW_BROWSER = None
    _PW = None
    # Ждём чтобы playwright-процесс успел завершиться
    await asyncio.sleep(3)


async def _ensure_browser():
    global _PW, _PW_BROWSER
    if _PW_BROWSER is not None:
        return True
    try:
        _PW = await async_playwright().start()
        _PW_BROWSER = await _PW.chromium.launch(
            headless=True,
            args=['--disable-blink-features=AutomationControlled'],
        )
        return True
    except Exception as e:
        print(f'  [Playwright] Failed to start browser: {e}')
        return False


async def _ensure_donedeal_page():
    global _DD_PAGE
    if _DD_PAGE is not None:
        return True
    if not await _ensure_browser():
        return False
    try:
        ctx = await _PW_BROWSER.new_context(**_PW_CONTEXT_OPTS)
        _DD_PAGE = await ctx.new_page()
        await _DD_PAGE.goto('https://www.donedeal.ie/cars', timeout=30000, wait_until='domcontentloaded')
        await _DD_PAGE.wait_for_timeout(2000)
        print('  [DoneDeal] Browser page ready')
        return True
    except Exception as e:
        print(f'  [DoneDeal] Failed to init page: {e}')
        return False


async def _ensure_carzone_page():
    global _CZ_PAGE
    if _CZ_PAGE is not None:
        return True
    if not await _ensure_browser():
        return False
    try:
        ctx = await _PW_BROWSER.new_context(**_PW_CONTEXT_OPTS)
        _CZ_PAGE = await ctx.new_page()
        await _CZ_PAGE.goto('https://www.carzone.ie/car-valuation', timeout=30000, wait_until='domcontentloaded')
        await _CZ_PAGE.wait_for_timeout(2000)
        try:
            await _CZ_PAGE.click('button:has-text("Accept")', timeout=3000)
            await _CZ_PAGE.wait_for_timeout(1000)
        except Exception:
            pass
        print('  [Carzone] Browser page ready')
        return True
    except Exception as e:
        print(f'  [Carzone] Failed to init page: {e}')
        return False


async def fetch_donedeal_page(url):
    """
    Fetches a DoneDeal search page via async Playwright (bypasses Cloudflare).
    Extracts __NEXT_DATA__ JSON. Returns (ads_list, paging_dict) or (None, None).
    При 429 — ждёт 15с и повторяет (до 3 раз).
    При обрыве соединения — пересоздаёт браузер и повторяет один раз.
    """
    await asyncio.sleep(5)
    print(f"  GET {url}")

    reconnected = False
    for attempt in range(3):  # до 3 попыток (включая 429-retry)
        if not await _ensure_donedeal_page():
            return None, None
        try:
            result = await _DD_PAGE.evaluate("""async (url) => {
                const r = await fetch(url, {
                    headers: {
                        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                        'Accept-Language': 'en-US,en;q=0.9',
                    }
                });
                return { status: r.status, body: await r.text() };
            }""", url)
        except Exception as e:
            print(f"  Request failed: {str(e)[:100]}")
            if not reconnected:
                print("  [DoneDeal] Reconnecting browser...")
                await _reset_playwright()
                reconnected = True
                continue
            return None, None

        if result['status'] == 429:
            print(f"  Error 429 (rate limit), waiting 20s...")
            await asyncio.sleep(20)
            continue

        if result['status'] != 200:
            print(f"  Error {result['status']}")
            return None, None

        break  # success
    else:
        return None, None

    soup = BeautifulSoup(result['body'], "html.parser")
    script_tag = soup.find("script", id="__NEXT_DATA__")
    if not script_tag or not script_tag.string:
        print("  __NEXT_DATA__ not found in HTML")
        return None, None
    try:
        data = json.loads(script_tag.string)
        page_props = data.get("props", {}).get("pageProps", {})
        return page_props.get("ads", []), page_props.get("paging", {})
    except (json.JSONDecodeError, KeyError) as e:
        print(f"  Error parsing __NEXT_DATA__: {e}")
        return None, None


async def get_carzone_valuation(registration, odom_str):
    """
    Запрашивает оценку авто на carzone.ie через async Playwright (обходит Cloudflare).
    Страница загружается один раз и переиспользуется.
    При обрыве соединения — пересоздаёт браузер и повторяет один раз.
    """
    if not registration or not registration.strip():
        return None
    try:
        odom_clean = re.sub(r'[,\s]', '', odom_str or '').lower()
        m = re.search(r'(\d+)', odom_clean)
        if not m:
            return None
        mileage = int(m.group(1))
        if 'mi' in odom_clean:
            mileage = int(mileage * 1.60934)

        api_path = f'/rest/1.0/Car/valuation?registration={registration.strip()}&mileage={mileage}&mileage_unit=km'

        result = None
        for attempt in range(2):
            if not await _ensure_carzone_page():
                return None
            try:
                result = await _CZ_PAGE.evaluate("""async (path) => {
                    const r = await fetch(path, {
                        headers: {
                            'Accept': 'application/json',
                            'Referer': 'https://www.carzone.ie/car-valuation',
                        }
                    });
                    return { status: r.status, body: await r.text() };
                }""", api_path)
                break
            except Exception as e:
                print(f"  [Carzone] Connection lost ({str(e)[:60]}), reconnecting...")
                await _reset_playwright()
                if attempt == 1:
                    return None

        if result is None:
            return None

        if result['status'] != 200:
            print(f"  [Carzone] Error {result['status']} for {registration}")
            return None

        data = json.loads(result['body'])
        v = data.get('valuationDetails', {})
        if not v or not v.get('retailExcellentPrice'):
            return None
        return {
            'retail_excellent': v.get('retailExcellentPrice'),
            'retail_standard':  v.get('retailStandardPrice'),
            'retail_poor':      v.get('retailPoorPrice'),
            'trade_excellent':  v.get('tradeExcellentPrice'),
            'trade_standard':   v.get('tradeStandardPrice'),
            'trade_poor':       v.get('tradePoorPrice'),
        }
    except Exception as e:
        print(f'  [Carzone] Exception for {registration}: {e}')
        return None


async def get_all_prices(url):
    """
    Fetches ALL pages of DoneDeal results and collects all prices (up to 10 pages).
    Returns sorted list of prices.
    """
    MAX_PAGES = 10
    all_prices = []
    separator = "&" if "?" in url else "?"

    for page_num in range(MAX_PAGES):
        page_url = url if page_num == 0 else f"{url}{separator}from={page_num * 30}"
        ads, paging = await fetch_donedeal_page(page_url)
        if ads is None:
            break
        total_results = paging.get("totalResults", 0) if paging else 0
        for ad in ads:
            price_info = ad.get("priceInfo", {})
            if price_info.get("priceOnRequest"):
                continue
            price_euro = price_info.get("priceInEuro")
            if price_euro and isinstance(price_euro, (int, float)) and price_euro > 0:
                all_prices.append(int(price_euro))
        if not ads or total_results <= (page_num + 1) * 30:
            break
        await asyncio.sleep(random.uniform(0.5, 1.0))

    if all_prices:
        print(f"  Collected {len(all_prices)} prices across {page_num + 1} page(s)")
    return sorted(all_prices)


async def get_avg(url):
    """Gets average price from DoneDeal via async Playwright."""
    return await get_avg_from_url(url)

# Add your main execution logic here if needed.
