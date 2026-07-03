import requests

url = "https://api.zenoti.com/v1/reports/sales/accrual_basis/flat_file"

payload = {
    "center_ids": ["05b67e63-aca8-4015-838e-7f9bd223a0fe"],
    "start_date": "2026-06-01 00:00:00",
    "end_date": "2026-06-01 23:59:00",
    "item_types": [-1],
    "sale_types": [-1],
    "payment_types": [-1],
    "sold_by_ids": [],
    "invoice_statuses": [-1],
    "vendors": {
        "ids": [],
        "is_all": True
    },
    "brands": {
        "ids": [],
        "is_all": True
    }
}
headers = {
    "accept": "application/json",
    "content-type": "application/json",
    "Authorization": "apikey b7623c5481f141b385821ebf3f640b64918caa56ea674279b87754b2b716d487"
}

response = requests.post(url, json=payload, headers=headers)

print(response.text)