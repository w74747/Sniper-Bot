import os
import requests
from dotenv import load_dotenv

load_dotenv()
url = f"https://solana-mainnet.g.alchemy.com/v2/{os.getenv('ALCHEMY_API_KEY')}"
payload = {"jsonrpc": "2.0", "id": 1, "method": "getHealth"}
response = requests.post(url, json=payload)
print("الحالة:", response.status_code)
print("الرد:", response.json())
