## Date helpers used by the options strategy.

from datetime import datetime

## Return calendar days between today and an ISO expiration date.
def calculate_dte(expiration: str) -> int:
    expiration_date = datetime.strptime(expiration, "%Y-%m-%d").date()
    today = datetime.today().date()
    return (expiration_date - today).days
