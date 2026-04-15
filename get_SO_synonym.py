import requests
import json
import time

def build_synonym_database(api_key):
    url = "https://api.stackexchange.com/2.3/tags/synonyms"
    synonym_map = {}
    page = 1
    has_more = True

    print("Starting data ingestion...")

    while has_more:
        params = {
            "order": "desc",
            "sort": "creation",
            "site": "stackoverflow",
            "pagesize": 100,
            "page": page,
            "key": api_key
        }

        response = requests.get(url, params=params)
        data = response.json()

        # 1. Respect Backoff (Rate Limiting)
        if 'backoff' in data:
            wait_time = data['backoff']
            print(f"Backoff received. Waiting {wait_time} seconds...")
            time.sleep(wait_time)

        # 2. Extract and Map
        for item in data.get('items', []):
            # Mapping: alias -> canonical_tag
            synonym_map[item['from_tag']] = item['to_tag']

        print(f"Processed page {page}. Total unique aliases: {len(synonym_map)}")

        # 3. Pagination Logic
        has_more = data.get('has_more', False)
        page += 1
        
        # Optional: Safety sleep to prevent aggressive polling
        time.sleep(0.1)

    # 4. Save to JSON
    with open('so_synonyms.json', 'w') as f:
        json.dump(synonym_map, f, indent=4)
    
    print("\nSuccess! Data saved to so_synonyms.json")

# Replace with your actual key
MY_API_KEY = "rl_7ANRAyN9S6F9AjbUVFt9K8Ahk"
build_synonym_database(MY_API_KEY)