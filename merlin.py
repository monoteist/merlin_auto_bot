import re
import time
import random
import asyncio
import json
import http.client
from bs4 import BeautifulSoup
import requests
import aiohttp

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
    Асинхронно собирает все данные о машинах с merlin.ie, затем получает цены с donedeal
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
    
    # Получаем ID аукциона из URL
    auction_id = auction_url.split('/')[-1] if '/' in auction_url else auction_url
    
    # Создаем aiohttp сессию
    async with aiohttp.ClientSession() as session:
        # STEP 1: Collect all car cards from all pages (asynchronously)
        print("\n" + "="*60)
        print("STEP 1: Collecting all car cards from all pages (asynchronously)")
        print("="*60)
        
        # First, determine total number of pages
        print("Determining number of pages...")
        first_page_url = f'https://www.merlin.ie/auction/{auction_id}'
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
            async with session.get(first_page_url, headers=headers, timeout=aiohttp.ClientTimeout(total=30)) as response:
                if response.status != 200:
                    print(f"Error loading first page: status {response.status}")
                    return
                
                html = await response.text()
                soup = BeautifulSoup(html, "html.parser")
                
                # Определяем максимальный номер страницы из пагинации
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
                    async with semaphore:  # Limit concurrent requests
                        try:
                            # Delay to avoid rate limiting
                            await asyncio.sleep(random.uniform(0.5, 1.5) * page_num)  # Different delay for different pages
                            
                            if page_num == 1:
                                page_url = f'https://www.merlin.ie/auction/{auction_id}'
                            else:
                                page_url = f'https://www.merlin.ie/auction/{auction_id}?page={page_num}'
                            
                            user_agent = get_random_user_agent()
                            headers = {
                                'User-Agent': user_agent,
                                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
                                'Accept-Language': 'en-US,en;q=0.9',
                                'Accept-Encoding': 'gzip, deflate, br',
                                'Connection': 'keep-alive',
                                'Upgrade-Insecure-Requests': '1',
                            }
                            
                            async with session.get(page_url, headers=headers, timeout=aiohttp.ClientTimeout(total=30)) as response:
                                if response.status != 200:
                                    print(f"  ✗ Page {page_num}: error status {response.status}")
                                    return []
                                
                                html = await response.text()
                                soup = BeautifulSoup(html, "html.parser")
                                
                                # Find all car cards
                                product_cards = soup.find_all('div', class_='product-card')
                                print(f"  ✓ Page {page_num}: found {len(product_cards)} cards")
                                
                                page_cars = []
                                
                                # Parse each card
                                for card in product_cards:
                                    car_data = {}
                                    
                                    # Vehicle link
                                    vehicle_link = card.find('a', href=re.compile(r'/vehicle/'))
                                    if vehicle_link:
                                        href = vehicle_link.get('href', '')
                                        car_data['lot_url'] = 'https://www.merlin.ie' + href if href.startswith('/') else href
                                    else:
                                        continue  # Skip if no link
                                    
                                    # Изображение
                                    img = card.find('img', class_='card-img-top')
                                    if img:
                                        img_src = img.get('src', '')
                                        if img_src:
                                            car_data['img_url'] = img_src
                                        else:
                                            car_data['img_url'] = '/images/comingsoon.jpg'
                                    else:
                                        car_data['img_url'] = '/images/comingsoon.jpg'
                                    
                                    # Lot number - extract from link inside div.card-lot
                                    lot_elem = card.find('div', class_='card-lot')
                                    if lot_elem:
                                        # Try to find link inside the div
                                        lot_link = lot_elem.find('a')
                                        if lot_link:
                                            lot_text = lot_link.get_text().strip()
                                            if lot_text:
                                                # Normalize the text (remove extra spaces)
                                                lot_text = ' '.join(lot_text.split())
                                                car_data['lot_number'] = lot_text
                                            # If no text in link, don't set lot_number
                                        # If no link found, don't set lot_number
                                    # If no card-lot element found, don't set lot_number
                                    
                                    # Регистрационный номер
                                    reg_elem = card.find('div', class_='card-reg')
                                    if reg_elem:
                                        car_data['registration'] = reg_elem.get_text().strip()
                                    
                                    # Make
                                    make_elem = card.find('h2', class_='card-title')
                                    if make_elem:
                                        make = make_elem.get_text().strip()
                                        car_data['make'] = make
                                    else:
                                        continue  # Skip if no make
                                    
                                    # Model (модель) - первый <p> после card-title
                                    card_title_wrap = card.find('div', class_='card-title-wrap')
                                    if card_title_wrap:
                                        paragraphs = card_title_wrap.find_all('p')
                                        if len(paragraphs) >= 1:
                                            car_data['model'] = paragraphs[0].get_text().strip()
                                        if len(paragraphs) >= 2:
                                            car_data['variant'] = paragraphs[1].get_text().strip()
                                    
                                    # Дата аукциона
                                    time_elem = card.find('li', class_='icon-item-time')
                                    if time_elem:
                                        date_text = time_elem.get_text().strip()
                                        date_match = re.search(r'(\d{2}/\d{2}/\d{4})', date_text)
                                        if date_match:
                                            car_data['date_auctions'] = date_match.group(1).replace('/', '.')
                                        else:
                                            car_data['date_auctions'] = date_text
                                    
                                    # Детали из details-list
                                    details_list = card.find('ul', class_='details-list')
                                    if details_list:
                                        detail_items = details_list.find_all('li', class_='detail-item')
                                        
                                        for item in detail_items:
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
                                    
                                    # Set default values
                                    if 'odom' not in car_data:
                                        car_data['odom'] = 'Unknown'
                                    if 'transmission' not in car_data:
                                        car_data['transmission'] = 'Unknown'
                                    if 'fuel' not in car_data:
                                        car_data['fuel'] = 'Unknown'
                                    if 'model' not in car_data:
                                        car_data['model'] = 'Unknown'
                                    
                                    # NCT and TAX will be obtained from detail page
                                    car_data['nct'] = 'Unknown'
                                    car_data['tax'] = 'Unknown'
                                    car_data['owners'] = 'Unknown'
                                    car_data['body'] = 'Unknown'
                                    
                                    # Form car_name for compatibility (year will be added later)
                                    car_data['car_name'] = f"{car_data.get('make', '')} {car_data.get('model', '')}"
                                    if car_data.get('variant'):
                                        car_data['car_name'] += f" {car_data['variant']}"
                                    
                                    # Save year as None, will get later
                                    car_data['year'] = None
                                    
                                    # Category notes and autoguru will be obtained from detail page
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
                page_semaphore = asyncio.Semaphore(5)  # Max 5 concurrent requests
                
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
            get_additional_details_from_vehicle_page_async(session, car_data['lot_url'], merlin_semaphore)
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
            
            # Обновляем Autoguru
            if details.get('autoguru'):
                car_data['autoguru'] = details['autoguru']
            
            # Обновляем cat_notes (очищенные)
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
            
            # Get price
            print(f"    Getting price from DoneDeal...")
            print(f"    DoneDeal URL: {car_data.get('donedal_link', 'N/A')}")
            avg, price_count = get_avg(car_data['donedal_link'])
            
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
            
            # Use random User-Agent
            user_agent = get_random_user_agent()
            headers = {
                'User-Agent': user_agent,
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
                'Accept-Language': 'en-US,en;q=0.9',
                'Accept-Encoding': 'gzip, deflate, br',
                'Connection': 'keep-alive',
                'Upgrade-Insecure-Requests': '1',
            }
            
            async with session.get(vehicle_url, headers=headers, timeout=aiohttp.ClientTimeout(total=30)) as response:
                if response.status != 200:
                    print(f"Error getting {vehicle_url}: status {response.status}")
                    return {}
                
                html = await response.text()
                soup = BeautifulSoup(html, "html.parser")
                
                # Save HTML for debugging (only for first few requests)
                import os
                debug_dir = "html_dumps"
                if not os.path.exists(debug_dir):
                    os.makedirs(debug_dir)
                # Save only first 3 pages for analysis
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
                    # Extract year (first 4-digit number)
                    year_match = re.search(r'\b(19|20)\d{2}\b', car_name)
                    if year_match:
                        details['year'] = year_match.group(0)
                
                # Look for NCT and TAX in details
                details_list = soup.find('ul', class_='details-list')
                if details_list:
                    detail_items = details_list.find_all('li', class_='detail-item')
                    print(f"  [DEBUG] Found {len(detail_items)} elements in details-list")
                    for item in detail_items:
                        span = item.find('span')
                        strong = item.find('strong')
                        
                        if span and strong:
                            label = span.get_text().strip()
                            value = strong.get_text().strip()
                            
                            # More flexible NCT search
                            if 'NCT' in label.upper() or 'National Car Test' in label:
                                # Save value even if it's "-" (this is a valid value)
                                if value:
                                    details['nct'] = value
                                elif value == '-':
                                    details['nct'] = '-'
                            # More flexible TAX search
                            elif 'TAX' in label.upper() or 'Tax Expiry' in label or 'Road Tax' in label:
                                # Save value even if it's "-"
                                if value:
                                    details['tax'] = value
                                elif value == '-':
                                    details['tax'] = '-'
                            elif 'Registered' in label:
                                # Extract year from registration date
                                year_match = re.search(r'/(\d{4})', value)
                                if year_match and 'year' not in details:
                                    details['year'] = year_match.group(1)
                
                # If NCT/TAX not found in details-list, search in other places
                if 'nct' not in details:
                    # Search for NCT in other places on page
                    nct_elem = soup.find(string=re.compile(r'NCT|National Car Test', re.I))
                    if nct_elem:
                        parent = nct_elem.find_parent(['li', 'div', 'span'])
                        if parent:
                            nct_text = parent.get_text()
                            nct_match = re.search(r'(\d{2}/\d{2}/\d{4})', nct_text)
                            if nct_match:
                                details['nct'] = nct_match.group(1)
                
                if 'tax' not in details:
                    # Search for TAX in other places on page
                    tax_elem = soup.find(string=re.compile(r'Tax Expiry|Road Tax', re.I))
                    if tax_elem:
                        parent = tax_elem.find_parent(['li', 'div', 'span'])
                        if parent:
                            tax_text = parent.get_text()
                            tax_match = re.search(r'(\d{2}/\d{2}/\d{4})', tax_text)
                            if tax_match:
                                details['tax'] = tax_match.group(1)
                
                # Look for Autoguru PDF link (from "View PDF" button)
                autoguru_link = None
                
                # 1. Look for link with class "btn btn-outline-secondary btn-block" and href containing "motorvehicleinspectionreport"
                autoguru_link = soup.find('a', class_=re.compile('btn.*btn-outline-secondary.*btn-block', re.I), href=re.compile('motorvehicleinspectionreport', re.I))
                
                # 2. If not found, look for any link with href containing "motorvehicleinspectionreport" and "pdf"
                if not autoguru_link:
                    autoguru_link = soup.find('a', href=re.compile('motorvehicleinspectionreport.*\.pdf', re.I))
                
                # 3. If not found, look for link with text "View PDF" and href containing "pdf"
                if not autoguru_link:
                    view_pdf_links = soup.find_all('a', string=re.compile('View PDF', re.I))
                    for link in view_pdf_links:
                        href = link.get('href', '')
                        if 'pdf' in href.lower() or 'motorvehicleinspectionreport' in href.lower():
                            autoguru_link = link
                            break
                
                # 4. If not found, look for link with href containing "autoguru"
                if not autoguru_link:
                    autoguru_link = soup.find('a', href=re.compile('autoguru', re.I))
                
                # 5. If not found, look by link text "autoguru"
                if not autoguru_link:
                    autoguru_links = soup.find_all('a', string=re.compile('autoguru', re.I))
                    if autoguru_links:
                        autoguru_link = autoguru_links[0]
                
                # 6. If link found, extract href
                if autoguru_link:
                    href = autoguru_link.get('href', '')
                    if href:
                        # Form full link
                        if href.startswith('/'):
                            details['autoguru'] = 'https://www.merlin.ie' + href
                        elif href.startswith('http'):
                            details['autoguru'] = href
                        else:
                            details['autoguru'] = 'https://www.merlin.ie/' + href
                    else:
                        # If href is empty, try data-href or other attributes
                        data_href = autoguru_link.get('data-href', '')
                        if data_href:
                            details['autoguru'] = 'https://www.merlin.ie' + data_href if data_href.startswith('/') else data_href
                
                # Look for lot number on detail page
                # Try to find in various places
                lot_number = None
                
                # 0. First, try to find in div.card-lot with link (as user specified)
                lot_elem = soup.find('div', class_='card-lot')
                if lot_elem:
                    lot_link = lot_elem.find('a')
                    if lot_link:
                        lot_text = lot_link.get_text().strip()
                        if lot_text:
                            lot_text = ' '.join(lot_text.split())  # Normalize spaces
                            lot_number = lot_text
                
                # 1. Look in span with class pill-item-lot (as in old code)
                lot_span = soup.find('span', class_='pill-item-lot')
                if lot_span:
                    lot_text = lot_span.get_text().strip()
                    # Look for number in format "Lot: 151" or just "151"
                    lot_match = re.search(r'Lot\s*:?\s*(\d+)', lot_text, re.I)
                    if lot_match:
                        lot_number = f"Lot: {lot_match.group(1)}"
                    elif lot_text and lot_text != 'TBC' and lot_text != 'Lot TBC':
                        # If text is not TBC, try to extract number
                        num_match = re.search(r'(\d+)', lot_text)
                        if num_match:
                            lot_number = f"Lot: {num_match.group(1)}"
                
                # 2. Look in other spans with class containing "lot"
                if not lot_number:
                    lot_elem = soup.find('span', class_=re.compile(r'lot|reference', re.I))
                    if lot_elem:
                        lot_text = lot_elem.get_text().strip()
                        lot_match = re.search(r'(\d+[A-Z]{0,2}\d{2,})', lot_text)
                        if lot_match:
                            lot_number = f"Lot: {lot_match.group(1)}"
                
                # 3. Look in page text by pattern "Lot: 151" or "Lot 151"
                if not lot_number:
                    lot_texts = soup.find_all(string=re.compile(r'Lot\s*:?\s*\d+', re.I))
                    for lot_text in lot_texts:
                        lot_match = re.search(r'Lot\s*:?\s*(\d+)', lot_text, re.I)
                        if lot_match:
                            lot_number = f"Lot: {lot_match.group(1)}"
                            break
                
                # 4. Look in headings or other places
                if not lot_number:
                    # Look in h1, h2, h3
                    for tag in ['h1', 'h2', 'h3', 'h4']:
                        headings = soup.find_all(tag)
                        for heading in headings:
                            heading_text = heading.get_text()
                            lot_match = re.search(r'Lot\s*:?\s*(\d+)', heading_text, re.I)
                            if lot_match:
                                lot_number = f"Lot: {lot_match.group(1)}"
                                break
                        if lot_number:
                            break
                
                if lot_number:
                    details['lot_number'] = lot_number
                
                # Look for category notes (cat_notes) - clean from garbage
                cat_notes = []
                seen_notes = set()  # For removing duplicates
                
                # Look for dealer information
                dealer_info = soup.find('div', class_=re.compile(r'dealer|seller|vendor', re.I))
                if dealer_info:
                    dealer_text = dealer_info.get_text().strip()
                    # Clean from extra spaces and line breaks
                    dealer_text = ' '.join(dealer_text.split())
                    if dealer_text and len(dealer_text) > 5 and len(dealer_text) < 100:
                        if dealer_text not in seen_notes:
                            cat_notes.append(dealer_text)
                            seen_notes.add(dealer_text)
                
                # Look for service history information
                service_info = soup.find(string=re.compile(r'service\s*history|stamp|stamps', re.I))
                if service_info:
                    parent = service_info.find_parent(['div', 'section', 'li'])
                    if parent:
                        service_text = parent.get_text().strip()
                        service_text = ' '.join(service_text.split())
                        # Extract only important information
                        if 'stamp' in service_text.lower() or 'service' in service_text.lower():
                            # Look for number of stamps
                            stamp_match = re.search(r'(\d+)\s*stamp', service_text, re.I)
                            if stamp_match:
                                stamp_count = stamp_match.group(1)
                                service_note = f"{stamp_count} Stamp Service History"
                                if service_note not in seen_notes:
                                    cat_notes.append(service_note)
                                    seen_notes.add(service_note)
                
                # Look for dealer information in text (e.g. "Joe Duffy Direct")
                page_text = soup.get_text()
                dealer_patterns = [
                    r'Joe\s+Duffy\s+Direct',
                    r'[A-Z][a-z]+\s+[A-Z][a-z]+\s+Direct',
                ]
                for pattern in dealer_patterns:
                    dealer_match = re.search(pattern, page_text)
                    if dealer_match:
                        dealer_name = dealer_match.group(0)
                        if dealer_name not in seen_notes:
                            cat_notes.append(dealer_name)
                            seen_notes.add(dealer_name)
                            break
                
                if cat_notes:
                    details['cat_notes'] = cat_notes
                
                # Look for Details (e.g. "See Autoguru report")
                details_text = None
                
                # 1. Look for text "See Autoguru report" on page
                see_autoguru = soup.find(string=re.compile(r'See\s+Autoguru\s+report', re.I))
                if see_autoguru:
                    details_text = see_autoguru.strip()
                else:
                    # 2. Look in links with text "See" or "View"
                    see_links = soup.find_all('a', string=re.compile(r'see|view', re.I))
                    for link in see_links:
                        link_text = link.get_text().strip()
                        if 'autoguru' in link_text.lower() or 'report' in link_text.lower():
                            details_text = link_text
                            break
                    
                    # 3. If not found, look in paragraphs or divs
                    if not details_text:
                        paragraphs = soup.find_all(['p', 'div', 'span'])
                        for p in paragraphs:
                            text = p.get_text().strip()
                            if 'see autoguru' in text.lower() or 'see report' in text.lower():
                                # Take short text
                                text_clean = ' '.join(text.split())
                                if len(text_clean) < 50:
                                    details_text = text_clean
                                    break
                
                # 4. If Autoguru PDF link exists but Details not found, add standard text
                if not details_text and details.get('autoguru'):
                    details_text = "See Autoguru report"
                
                if details_text:
                    details['details'] = details_text
                
                # Debug output
                print(f"  [DEBUG] Extracted from {vehicle_url}:")
                print(f"    - NCT: {details.get('nct', 'N/A')}")
                print(f"    - TAX: {details.get('tax', 'N/A')}")
                print(f"    - Autoguru: {details.get('autoguru', 'N/A')}")
                print(f"    - Details: {details.get('details', 'N/A')}")
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
        # Новый подход: парсим данные со страницы аукциона асинхронно
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
                new_loop = asyncio.new_event_loop()
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
            # Event loop not running, create new one
            try:
                loop = asyncio.get_event_loop()
                if loop.is_closed():
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
            except RuntimeError:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
            
            loop.run_until_complete(get_cars_async(url, user_id, bot))
    else:
        # Old approach: through separate pages (for backward compatibility)
        print("Using old approach: through separate pages")
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
            _wait_between_requests()  # Задержка между запросами
            
            try:
                response = requests.get(link, headers=headers, timeout=30)
                response.raise_for_status()
                soup = BeautifulSoup(response.text, "html.parser")
            except Exception as e:
                print(f"Error loading {link}: {e}")
                continue

            # Car name
            h1 = soup.find('h1', class_='title-h1')
            if h1:
                data['car_name'] = h1.get_text().strip()
            else:
                continue  # Skip if can't find name

            # Lot number
            lot_span = soup.find('span', class_='pill-item-lot')
            if lot_span:
                lot_text = lot_span.get_text().strip()
                # Убеждаемся, что получаем полный номер лота
                if lot_text and len(lot_text) > 3:  # Минимум "Lot X"
                    data['lot_number'] = lot_text
                else:
                    # Try to find in parent element
                    parent = lot_span.parent
                    if parent:
                        parent_text = parent.get_text().strip()
                        lot_match = re.search(r'Lot\s*:?\s*\d+', parent_text, re.I)
                        if lot_match:
                            data['lot_number'] = lot_match.group(0)
                        else:
                            data['lot_number'] = lot_text if lot_text else 'Lot: Unknown'
                    else:
                        data['lot_number'] = 'Lot: Unknown'
            else:
                data['lot_number'] = 'Lot: Unknown'

            # Auction date
            time_span = soup.find('span', class_='pill-item-time')
            if time_span:
                date_text = time_span.get_text().strip()
                # Extract date from format "10:30AM - 23/01/2026"
                date_match = re.search(r'(\d{2}/\d{2}/\d{4})', date_text)
                if date_match:
                    data['date_auctions'] = date_match.group(1).replace('/', '.')
                else:
                    data['date_auctions'] = date_text
            else:
                data['date_auctions'] = 'Unknown'

            # Image
            gallery_img = soup.find('div', class_='ug-slider-inner')
            if gallery_img:
                first_img = gallery_img.find('img')
                if first_img:
                    img_src = first_img.get('src', '')
                    if img_src:
                        data['img_url'] = img_src
            if 'img_url' not in data:
                # Alternative search
                all_imgs = soup.find_all('img', src=re.compile(r'merlin-prod-data-s3-public|motorvehicle'))
                if all_imgs:
                    data['img_url'] = all_imgs[0].get('src', '')
                else:
                    data['img_url'] = '/images/comingsoon.jpg'

            data['lot_url'] = link

            # Car details from list
            details_list = soup.find('ul', class_='details-list')
            if details_list:
                detail_items = details_list.find_all('li', class_='detail-item')
                
                for item in detail_items:
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

            # Set default values if not found
            if 'odom' not in data:
                data['odom'] = 'Unknown'
            if 'transmission' not in data:
                data['transmission'] = 'Unknown'
            if 'fuel' not in data:
                data['fuel'] = 'Unknown'
            if 'nct' not in data:
                data['nct'] = 'Unknown'
            if 'tax' not in data:
                data['tax'] = 'Unknown'
            if 'owners' not in data:
                data['owners'] = 'Unknown'
            if 'body' not in data:
                data['body'] = 'Unknown'

            # Category notes
            content_sections = soup.find_all('div', class_='content-section')
            cat_notes = []
            for section in content_sections:
                paragraphs = section.find_all('p')
                for p in paragraphs:
                    text = p.get_text().strip()
                    if text and len(text) > 10 and text not in cat_notes:
                        cat_notes.append(text)
            data['cat_notes'] = cat_notes if cat_notes else []

            # Autoguru (if exists)
            autoguru_link = soup.find('a', href=re.compile('autoguru', re.I))
            if autoguru_link:
                href = autoguru_link.get('href', '')
                if href:
                    data['autoguru'] = 'https://www.merlin.ie' + href if href.startswith('/') else href

            data['donedal_link'] = get_donedeal_link(data['car_name'], data['transmission'], data['fuel'])
            
            # Debugging: Print the DoneDeal link
            print(f"DoneDeal Link: {data['donedal_link']}")
            
            avg, price_count = get_avg(data['donedal_link'])

            if avg is not None:
                data['avg'] = avg
                data['total'] = price_count
            else:
                data['avg'] = None
                data['total'] = None
            
            print(data)  # Debugging: print data to see what is being sent

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
            response = requests.get(f"https://www.merlin.ie{img_url}", timeout=10)
        else:
            response = requests.get(img_url, timeout=10)
        
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
            
            # 3. Transmission, Fuel, Odometer в одной строке через запятую
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
            
            # 6. AVG price (if exists) - monospace format
            if i.get('avg') is not None and i.get('total') is not None:
                avg_price = int(i['avg'])
                total_count = i['total']
                caption += f"<code>AVG: €{avg_price} ({total_count})</code>\n"
            
            # 7. DoneDeal link (hidden under text)
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
        # Process make with hyphen (e.g. "Mercedes-benz")
        make_part = parts[1]
        if '-' in make_part:
            # "Mercedes-benz" -> "MERCEDES-BENZ" for URL
            make = make_part.upper()
        else:
            make = make_part.upper()
        model = parts[2].upper() if len(parts) > 2 else ''
    
    base = 'https://www.donedeal.ie/cars'
    
    # Normalize transmission and fuel
    trans = trans.upper() if trans else 'Manual'
    fuel = fuel.upper() if fuel else 'Diesel'
    
    # Normalize complex fuel types for URL (take first part)
    if '/' in fuel:
        fuel = fuel.split('/')[0].strip()
    
    # Mapping for special cases (for URL encoding)
    make_url_mapping = {
        'MERCEDES-BENZ': 'Mercedes%20Benz',
        'MERCEDESBENZ': 'Mercedes%20Benz',
    }
    make_url = make_url_mapping.get(make, make.replace('-', '%20'))
    
    # Extract additional information from name if needed
    variant = ''
    if len(parts) > 3:
        variant = ' '.join(parts[3:]).upper()

    # Build the DoneDeal link based on make and model
    if 'LANDROVER' in make or make == 'LANDROVER':
        if model == 'RANGEROVER':
            if variant and any(v in variant for v in ['VELAR', 'SPORT', 'EVOQUE']):
                variant_part = variant.split()[0] if variant.split() else ''
                return f"{base}/Land%20Rover/Range%20Rover%20{variant_part}/{year}?transmission={trans}&fuelType={fuel}"
            else:
                return f"{base}/Land%20Rover/Range%20Rover/{year}?transmission={trans}&fuelType={fuel}"

        elif model == 'DISCOVERY':
            if variant and 'SPORT' in variant:
                return f"{base}/Land%20Rover/Discovery%20Sport/{year}?transmission={trans}&fuelType={fuel}"
            else:
                return f"{base}/Land%20Rover/Discovery/{year}?transmission={trans}&fuelType={fuel}"

        else:
            return f"{base}/Land%20Rover/{model}/{year}?transmission={trans}&fuelType={fuel}"

    elif make == 'CITROEN':
        if model == 'C4':
            if variant and 'GRAND PICASSO' in variant:
                return f"{base}?make=Citroen;model:C4%20GRAND%20PICASSO,Grand%20C4%20Picasso&transmission={trans}&fuelType={fuel}&year_from={year}&year_to={year}"

            elif variant and any(v in variant for v in ['PICASSO', 'CACTUS']):
                variant_part = variant.split()[0] if variant.split() else ''
                return f"{base}/Citroen/{model}%20{variant_part}/{year}?transmission={trans}&fuelType={fuel}"

            else:
                return f"{base}/Citroen/{model}/{year}?transmission={trans}&fuelType={fuel}"
        elif model == 'C3':
            return f"{base}/Citroen/{model}/{year}?transmission={trans}&fuelType={fuel}"
    
    # Additional logic for other makes/models...

    else:
        # Use make_url for correct URL encoding
        return f"{base}/{make_url}/{model}/{year}?transmission={trans}&fuelType={fuel}"

def get_avg_from_url(url):
    """
    Extracts parameters from DoneDeal URL and gets average price via API
    URL format: https://www.donedeal.ie/cars/MAKE/MODEL/YEAR?transmission=MANUAL&fuelType=DIESEL
    """
    try:
        # Parse URL to extract parameters
        from urllib.parse import urlparse, parse_qs
        
        parsed = urlparse(url)
        path_parts = [p for p in parsed.path.split('/') if p]
        
        # Format: /cars/MAKE/MODEL/YEAR
        if len(path_parts) < 4 or path_parts[0] != 'cars':
            print(f"Invalid URL format: {url}")
            return None, 0
        
        make = path_parts[1]
        model = path_parts[2]
        year = path_parts[3]
        
        # Parse query parameters
        query_params = parse_qs(parsed.query)
        transmission = query_params.get('transmission', [''])[0].upper()
        fuel_type = query_params.get('fuelType', [''])[0].upper()
        
        # Normalize fuel type for API (remove complex combinations)
        if '/' in fuel_type:
            # If fuel type is "PETROL/PLUG-IN HYBRID ELECTRIC", take first part
            fuel_type = fuel_type.split('/')[0].strip()
        if 'HYBRID' in fuel_type or 'ELECTRIC' in fuel_type:
            # For hybrids and electric use "Petrol" or "Diesel" depending on first part
            if 'PETROL' in fuel_type or 'PETROL' in fuel_type.split('/')[0] if '/' in fuel_type else fuel_type:
                fuel_type = 'Petrol'
            elif 'DIESEL' in fuel_type or 'DIESEL' in fuel_type.split('/')[0] if '/' in fuel_type else fuel_type:
                fuel_type = 'Diesel'
            else:
                fuel_type = 'Petrol'  # Default
        
        print(f"Parsing URL: make={make}, model={model}, year={year}, transmission={transmission}, fuel={fuel_type}")
        
        # Form parameters for API request
        filters = []
        if transmission:
            filters.append({"name": "transmission", "values": [transmission]})
        if fuel_type:
            filters.append({"name": "fuelType", "values": [fuel_type]})
        
        ranges = [
            {"name": "price", "from": "300", "to": "100000"},
            {"name": "year", "from": year, "to": year}
        ]
        
        make_model = [{"model": model, "make": make}]
        
        car_params = {
            "sections": ["cars"],
            "filters": filters,
            "ranges": ranges,
            "paging": {"pageSize": 40, "from": 0},
            "sort": "",
            "makeModelFilters": make_model,
            "terms": "",
        }
        
        # Try with all filters first
        avg, count = get_avg_from_api(car_params)
        if avg is not None:
            return avg, count
        
        # Fallback 1: Try without transmission filter
        print(f"  [FALLBACK] Trying without transmission filter...")
        filters_no_trans = [f for f in filters if f["name"] != "transmission"]
        if len(filters_no_trans) < len(filters):
            car_params_fallback = car_params.copy()
            car_params_fallback["filters"] = filters_no_trans
            avg, count = get_avg_from_api(car_params_fallback)
            if avg is not None:
                print(f"  ✓ Price found without transmission filter")
                return avg, count
        
        # Fallback 2: Try without fuel type filter
        print(f"  [FALLBACK] Trying without fuel type filter...")
        filters_no_fuel = [f for f in filters if f["name"] != "fuelType"]
        if len(filters_no_fuel) < len(filters):
            car_params_fallback = car_params.copy()
            car_params_fallback["filters"] = filters_no_fuel
            avg, count = get_avg_from_api(car_params_fallback)
            if avg is not None:
                print(f"  ✓ Price found without fuel type filter")
                return avg, count
        
        # Fallback 3: Try without any filters (only make, model, year)
        print(f"  [FALLBACK] Trying without any filters (only make/model/year)...")
        car_params_fallback = car_params.copy()
        car_params_fallback["filters"] = []
        avg, count = get_avg_from_api(car_params_fallback)
        if avg is not None:
            print(f"  ✓ Price found without filters")
            return avg, count
        
        # Fallback 4: Try with expanded year range (±2 years)
        try:
            year_int = int(year)
            print(f"  [FALLBACK] Trying with expanded year range ({year_int-2} to {year_int+2})...")
            car_params_fallback = car_params.copy()
            car_params_fallback["filters"] = []
            car_params_fallback["ranges"] = [
                {"name": "price", "from": "300", "to": "100000"},
                {"name": "year", "from": str(year_int-2), "to": str(year_int+2)}
            ]
            avg, count = get_avg_from_api(car_params_fallback)
            if avg is not None:
                print(f"  ✓ Price found with expanded year range")
                return avg, count
        except (ValueError, TypeError):
            pass
        
        # Fallback 5: Try without year (only make and model)
        print(f"  [FALLBACK] Trying without year (only make/model)...")
        car_params_fallback = car_params.copy()
        car_params_fallback["filters"] = []
        car_params_fallback["ranges"] = [
            {"name": "price", "from": "300", "to": "100000"}
        ]
        avg, count = get_avg_from_api(car_params_fallback)
        if avg is not None:
            print(f"  ✓ Price found without year")
            return avg, count
        
        # Fallback 6: Try with model name variations (remove hyphens)
        if '-' in model:
            model_variant = model.replace('-', ' ')
            print(f"  [FALLBACK] Trying with model variant '{model_variant}' (without hyphen)...")
            car_params_fallback = car_params.copy()
            car_params_fallback["filters"] = []
            car_params_fallback["ranges"] = [
                {"name": "price", "from": "300", "to": "100000"}
            ]
            car_params_fallback["makeModelFilters"] = [{"model": model_variant, "make": make}]
            avg, count = get_avg_from_api(car_params_fallback)
            if avg is not None:
                print(f"  ✓ Price found with model variant")
                return avg, count
        
        print(f"  ✗ Price not found even with fallback searches")
        return None, 0
        
    except Exception as e:
        print(f"Error parsing URL {url}: {e}")
        return None, 0

def get_avg_from_api(car_params: dict):
    """
    Gets average price via DoneDeal API (as in donedeal_bot)
    """
    try:
        # Add delay between requests
        _wait_between_requests()
        
        uri = "/ddapi/v1/search"
        host = "www.donedeal.ie"
        payload_json = json.dumps(car_params)
        
        user_agent = get_random_user_agent()
        headers = {
            "Accept": "application/json",
            "Accept-Language": "en-US,en;q=0.9",
            "Brand": "donedeal",
            "Content-Type": "application/json",
            "User-Agent": user_agent,
            "Origin": "https://www.donedeal.ie",
            "Referer": "https://www.donedeal.ie/cars",
        }
        
        conn = http.client.HTTPSConnection(host, timeout=30)
        try:
            print(f"Sending API request to {host}{uri}")
            conn.request("POST", uri, body=payload_json, headers=headers)
            response = conn.getresponse()
            data = response.read()
            data_decoded = data.decode("utf-8")
            
            if response.status == 200:
                result = json.loads(data_decoded)
                
                # Check different possible response structures
                ads = None
                if "ads" in result:
                    ads = result.get("ads", [])
                elif "data" in result and isinstance(result["data"], dict):
                    # Possibly data in data.ads
                    ads = result["data"].get("ads", [])
                elif "data" in result and isinstance(result["data"], list):
                    # Possibly data is a list of ads
                    ads = result["data"]
                
                if not ads or (isinstance(ads, list) and len(ads) == 0):
                    print("  [DEBUG] No ads found in API response")
                    print(f"  [DEBUG] Keys in response: {list(result.keys())}")
                    if "paging" in result:
                        paging_info = result['paging']
                        print(f"  [DEBUG] paging: {paging_info}")
                        if paging_info.get('totalResults', 0) == 0:
                            print(f"  [INFO] No listings found for this search criteria")
                    return None, 0
                
                if not isinstance(ads, list):
                    print(f"  [DEBUG] ads is not a list, type: {type(ads)}")
                    return None, 0
                print(f"Found ads: {len(ads)}")
                
                prices = []
                for ad in ads:
                    if ad.get("currency") == "EUR":
                        try:
                            price_str = ad.get("price", "").replace(",", "")
                            if price_str:
                                price_value = int(price_str)
                                if price_value > 0:
                                    prices.append(price_value)
                        except (ValueError, KeyError):
                            continue
                
                if prices:
                    average_price = sum(prices) / len(prices)
                    print(f"  ✓ Average price: €{int(average_price)} ({len(prices)} ads)")
                    return average_price, len(prices)
                else:
                    print(f"  ✗ No valid prices found in {len(ads)} ads (all prices may be in different currency or invalid)")
                    return None, 0
                    
            elif response.status == 403:
                print("Error 403: Possible Cloudflare blocking")
                return None, 0
            else:
                print(f"API error: status {response.status}")
                return None, 0
                
        finally:
            conn.close()
            
    except Exception as e:
        print(f"Error getting prices via API: {e}")
        import traceback
        traceback.print_exc()
        return None, 0

def get_avg(url):
    """Gets average price from DoneDeal via API (as in donedeal_bot)"""
    return get_avg_from_url(url)

# Add your main execution logic here if needed.
