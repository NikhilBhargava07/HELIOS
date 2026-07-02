## Date helpers used by the options strategy.

from datetime import datetime

## Calculate days to expiration from an expiration date string.
## DTE filtering keeps recommendations inside the strategy’s preferred option lifetime.
def calculate_dte(expiration: str) -> int:
    expiration_date = datetime.strptime(expiration, "%Y-%m-%d").date()
    today = datetime.today().date()
    return (expiration_date - today).days
