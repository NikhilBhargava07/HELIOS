from datetime import datetime

def calculate_dte(expiration: str) -> int:
    # expiration comes in as a string like "2026-06-19"
    expiration_date = datetime.strptime(expiration, "%Y-%m-%d").date()

    # today's date
    today = datetime.today().date()

    # difference between expiration date and today
    dte = (expiration_date - today).days

    return dte

# def filter_by_delta():