## Coerce the loosely typed numbers HELIOS receives into usable floats.
##
## Broker fields arrive as strings, DynamoDB returns Decimals, and pandas fills a
## missing value with NaN. All three need the same answer, so the conversion lives
## in one place rather than being redefined beside each caller.

import math


## Return a float, or None when the value is missing or not a number.
##
## NaN counts as missing on purpose. It is not a quantity, it silently poisons any
## arithmetic it touches, and it is neither valid JSON nor a value DynamoDB accepts,
## so letting it through would push a broken number further into the system.
def number_or_none(value):
    if value is None:
        return None

    try:
        number = float(value)
    except (TypeError, ValueError):
        return None

    return None if math.isnan(number) else number
