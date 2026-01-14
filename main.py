import requests
from bs4 import BeautifulSoup
import re

def get_price_from_page(url):
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/58.0.3029.110 Safari/537.3'
        }

        response = requests.get(url, headers=headers)
        response.raise_for_status()  # Raise an error for bad responses

        soup = BeautifulSoup(response.content.decode('utf-8', errors='replace'), 'html.parser')

        # Print fetching URL for debugging
        print(f"Fetching URL: {url}")
        print("Response Status Code:", response.status_code)

        # Find all the listings with the specific class
        listings = soup.find_all(class_='Listingsstyled__ListItem-sc-mwopjh-2 ikTiBs')
        prices = []

        # Iterate through the listings and extract prices
        for listing in listings:
            # Search for all price text within each listing
            price_texts = listing.find_all(text=re.compile(r'€[\d,]+'))
            valid_prices = []

            for price_text in price_texts:
                price_value = re.search(r'€[\d,]+', price_text)
                if price_value:
                    clean_price = price_value.group(0).strip()
                    # Apply the new conditions
                    if clean_price[0] == '€' and clean_price != '€0' and clean_price != '€1,234':
                        valid_prices.append(clean_price)  # Keep it as a string for now
            
            # If we found valid prices, prioritize the first one
            if valid_prices:
                main_price = valid_prices[0]  # Get the main price
                prices.append(main_price)  # Store the main price
                print(f"Main price found: {main_price} in listing: {listing.get_text()}")

        # Get the length of filtered prices
        price_count = len(prices)
        print(prices)
        print(f"Number of valid prices found: {price_count}")

        # Calculate average price if we have valid prices
        if prices:
            # Convert prices to numeric values
            numeric_prices = [float(price.replace('€', '').replace(',', '')) for price in prices]
            total_sum = sum(numeric_prices)
            average_price = total_sum / price_count  # Calculate average
            print(f"Total Sum of Prices: €{total_sum:.2f}")
            print(f"Average Price: €{average_price:.2f}")
            return prices, price_count, average_price

        print("No valid price found on this page.")
        return None, 0, 0

    except requests.HTTPError as http_err:
        print(f"HTTP error occurred: {http_err}")
        return None, 0, 0
    except Exception as e:
        print(f"An unexpected error occurred: {e}")
        return None, 0, 0

# Test the function with the URL
url = "https://www.donedeal.ie/cars/VOLKSWAGEN/TIGUAN/2023?transmission=Manual&fuelType=Diesel"
get_price_from_page(url)
