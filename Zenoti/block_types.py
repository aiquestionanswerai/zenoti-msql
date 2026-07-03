import requests

url = "https://api.zenoti.com/v1/organizations/blockouttimes/types?page=1&size=100"

headers = {
    "accept": "application/json",
    "Authorization": "apikey b7623c5481f141b385821ebf3f640b64918caa56ea674279b87754b2b716d487"
}

response = requests.get(url, headers=headers)

print(response.text)