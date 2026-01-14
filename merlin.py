import re
import time
from bs4 import BeautifulSoup
from selenium import webdriver
import requests
from selenium.webdriver.common.by import By

print("OK")

def get_url():
    print("working")
    driver = webdriver.Chrome()
    driver.get('https://www.merlin.ie/')

    driver.find_element(By.LINK_TEXT, "View Catalogue Now").click()
    time.sleep(2)
    driver.find_element(By.LINK_TEXT, "1").click()
    time.sleep(2)

    current_url = driver.current_url
    response = driver.page_source
    driver.quit()

    soup = BeautifulSoup(response, "html.parser")
    sort_box = soup.find_all('div', class_='sort_box')[1]
    car_count = sort_box.find('span').text

    url = current_url.replace('&pagesize=25', f"&pagesize={car_count}")
    return url

def get_car_link(url):
    driver = webdriver.Chrome()
    driver.get(url)
    time.sleep(10)
    response = driver.page_source

    driver.quit()

    soup = BeautifulSoup(response, "html.parser")
    main_block = soup.find_all('div', class_='car_features_area')[1]
    cars = main_block.find_all('div', class_='car_box')

    links = []

    for car in cars:
        h5 = car.find('h5')
        links.append('https://www.merlin.ie/' + h5.find('a')['href'])

    return links

def get_cars(url, user_id, bot):
    links = get_car_link(url)
    driver = webdriver.Chrome()
    for link in links:
        data = {}
        driver.get(link)
        time.sleep(2)
        response = driver.page_source
        soup = BeautifulSoup(response, "html.parser")
        car = soup.find('div', class_='details_sec')

        data['img_url'] = car.find('img')['src'].replace(' ', '%20')
        data['car_name'] = car.find('h5').text.strip()
        data['lot_url'] = link
        data['lot_number'] = car.find_all('em')[1].text

        car_info_div = car.find('div', class_='dateList')
        car_info_span = car.find_all('span', class_="ng-binding")
        car_detail_div = car.find('div', class_='addconts')

        data['date_auctions'] = car_info_span[0].text[:8].replace('/', '.')
        data['odom'] = car_info_span[1].text
        data['nct'] = car_info_span[2].text.strip()
        data['tax'] = car_info_span[3].text.strip()
        data['owners'] = car_info_span[5].text
        data['fuel'] = car_info_span[8].text
        data['body'] = car_info_span[9].text
        data['transmission'] = car_info_span[10].text
        data['cat_notes'] = [note.text for note in car_info_div.find_all('p')]
        details = car_detail_div.find('p').text.split('\n')[1].strip()
        if details:
            data['details'] = details
        if 'inline' in soup.find('a', id='autoguruReport')['style']:
            data['autoguru'] = f"https://www.merlin.ie/{soup.find('a', id='autoguruReport')['href']}"

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
    driver.quit()

def send_car(i, user_id, bot):
    if i['img_url'].startswith('/images/comingsoon.jpg'):
        response = requests.get(f"https://www.merlin.ie{i['img_url']}")
    else:
        response = requests.get(i['img_url'])
    if response.status_code == 200:
        caption = f"<pre style='text-align: center'>{i['lot_number']}</pre>\n" \
                  f"<a href='{i['lot_url']}'>{i['car_name']}</a>\n\n" \
                  f"🕹️ {i['transmission']}\n" \
                  f"⛽️ {i['fuel']}\n" \
                  f"📟 {i['odom']}\n" \
                  f"<b>NCT:</b> {i['nct']}\n" \
                  f"<b>TAX:</b> {i['tax']}\n\n"

        if 'autoguru' in i:
            caption += f"<a href='{i['autoguru']}'>Autoguru</a>\n\n"

        if 'details' in i:
            a = '\n'
            caption += f"<b>Notes:</b> {a.join(i['cat_notes'])}\n"
            caption += f"<b>Details:</b> {i['details']}\n\n"

        else:
            caption += f"<b>Notes:</b> {' '.join(i['cat_notes'])}\n\n"
        if i['avg'] is not None and i['total'] is not None:
            caption += f"<pre style='text-align: center'>AVG: €{int(i['avg'])} ({i['total']}) </pre>\n"

        caption += f"<a href='{i['donedal_link']}'>DoneDeal</a>"

        if i['lot_number'] == 'Lot: 1':
            to_pin = bot.send_message(user_id, f"{i['date_auctions']}", parse_mode='HTML')
            bot.pin_chat_message(user_id, message_id=to_pin.message_id)
        bot.send_photo(user_id, response.content, caption=caption, parse_mode='HTML')
    else:
        bot.reply_to(user_id, 'Не удалось загрузить изображение.')

def get_donedeal_link(car_name, trans, fuel):
    year = car_name.split(' ')[0]
    make = car_name.split(' ')[1]
    model = car_name.split(' ')[2]
    base = 'https://www.donedeal.ie/cars'

    # Build the DoneDeal link based on make and model
    if make == 'LANDROVER':
        if model == 'RANGEROVER':
            if car_name.split(' ')[3] in ['VELAR', 'SPORT', 'EVOQUE']:
                return f"{base}/Land%20Rover/Range%20Rover%20{car_name.split(' ')[3]}/{year}?transmission={trans}&fuelType={fuel}"
            else:
                return f"{base}/Land%20Rover/Range%20Rover/{year}?transmission={trans}&fuelType={fuel}"

        elif model == 'DISCOVERY':
            if car_name.split(' ')[3] in ['SPORT']:
                return f"{base}/Land%20Rover/Discovery%20{car_name.split(' ')[3]}/{year}?transmission={trans}&fuelType={fuel}"
            else:
                return f"{base}/Land%20Rover/Discovery/{year}?transmission={trans}&fuelType={fuel}"

        else:
            return f"{base}/Land%20Rover/{model}/{year}?transmission={trans}&fuelType={fuel}"

    elif make == 'CITROEN':
        if model == 'C4':
            if car_name.split(' ')[3] in ['GRAND PICASSO']:
                return f"{base}?make=Citroen;model:C4%20GRAND%20PICASSO,Grand%20C4%20Picasso&transmission={trans}&fuelType={fuel}&year_from={year}&year_to={year}"

            elif car_name.split(' ')[3] in ['PICASSO', 'CACTUS']:
                return f"{base}/{make}/{model}%20{car_name.split(' ')[3]}/{year}?transmission={trans}&fuelType={fuel}"

            else:
                return f"{base}/{make}/{model}/{year}?transmission={trans}&fuelType={fuel}"
        elif model == 'C3':
            return f"{base}/{make}/{model}/{year}?transmission={trans}&fuelType={fuel}"
    
    # Additional logic for other makes/models...

    else:
        return f"{base}/{make}/{model}/{year}?transmission={trans}&fuelType={fuel}"

def get_avg(url):
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/58.0.3029.110 Safari/537.3'
        }

        # Print the URL being fetched
        print(f"Fetching URL: {url}")  
        response = requests.get(url, headers=headers)
        response.raise_for_status()

        print("Response Status Code:", response.status_code)  # Debugging: Print status code

        # Parse the content of the page
        soup = BeautifulSoup(response.content.decode('utf-8', errors='replace'), 'html.parser')

        # Print the content for inspection (optional, may be large)
        # print("Page content:", soup.prettify())  # Uncomment for detailed content

        # Attempt to find listings by common class identifiers
        listings = soup.find_all(class_='Listingsstyled__ListItem-sc-mwopjh-2 ikTiBs') or soup.find_all('div', class_='listing-item')
        
        print(f"Number of listings found: {len(listings)}")  # Debugging: Number of listings found
        prices = []

        for listing in listings:
            # Look for price elements (you may need to update this based on current HTML)
            price_element = listing.find(class_='Price__Amount-sc-1r5gbtp-2') or listing.find(class_='price') or listing.find(class_='listing-price')
            if price_element:
                price_text = price_element.get_text(strip=True)
                print(f"Raw price text found: {price_text}")  # Debugging: Print raw price text

                if price_text.startswith('€'):
                    clean_price = price_text[1:].replace(',', '').strip()
                    try:
                        price_value = int(clean_price)
                        if price_value > 0:  # Ensure prices are greater than 0
                            prices.append(price_value)
                            print(f"Valid price found: €{price_value}")  # Debugging: Valid price
                    except ValueError:
                        print("Skipping invalid price:", price_text)  # Debugging: Invalid price

        price_count = len(prices)
        if price_count > 0:
            average_price = sum(prices) / price_count
            print(f"Collected Prices: {prices}")  # Debugging: Collected prices
            print(f"Average Price: €{average_price:,.2f}")  # Debugging: Average price
            return average_price, price_count
        else:
            print("No valid prices found.")  # Debugging: No valid prices
            return None, 0

    except Exception as e:
        print(f"An unexpected error occurred: {e}")  # General exception handling
        return None, 0

# Add your main execution logic here if needed.
