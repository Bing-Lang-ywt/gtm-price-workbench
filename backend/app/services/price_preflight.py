"""Pure input diagnostics; no persistence, FX lookup, crawling or notifications."""
import math

SUPPORTED_CURRENCIES = frozenset({'EUR', 'RSD', 'HUF', 'RON', 'BGN', 'PLN', 'CZK'})
SUPPORTED_PRICE_TYPES = frozenset({'unlocked', 'contract_monthly', 'subsidy_down_payment'})


def preflight_price(price, price_type, currency):
    issues = []
    if isinstance(price, bool) or not isinstance(price, (int, float)):
        issues.append({'field': 'price', 'code': 'not_numeric',
                       'message': 'Price must be a number, not a boolean or numeric string.'})
    else:
        try:
            finite = math.isfinite(price)
        except OverflowError:
            finite = False
        if not finite:
            issues.append({'field': 'price', 'code': 'not_finite',
                           'message': 'Price must be finite.'})
        elif price <= 0:
            issues.append({'field': 'price', 'code': 'not_positive',
                           'message': 'Preview requires a price greater than zero.'})
    if not isinstance(price_type, str) or price_type not in SUPPORTED_PRICE_TYPES:
        issues.append({'field': 'price_type', 'code': 'unsupported_price_type',
                       'message': 'Price type must be unlocked, contract_monthly or subsidy_down_payment.'})
    if not isinstance(currency, str) or currency not in SUPPORTED_CURRENCIES:
        issues.append({'field': 'currency', 'code': 'unsupported_currency',
                       'message': 'Currency must be EUR, RSD, HUF, RON, BGN, PLN or CZK.'})
    return {'valid': not issues, 'issues': issues}
