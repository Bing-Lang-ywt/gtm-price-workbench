"""Offline normalization; no proprietary label files or deployment data."""
from app.integrations.eprel import normalize


def test_normalize_fictional_label():
    result = normalize({'modelIdentifier': 'DEMO-ONE', 'eprelRegistrationNumber': 9999999,
                        'deviceType': 'SMARTPHONE', 'energyClass': 'B',
                        'supplierOrTrademark': 'DemoBrand', 'ratedBatteryCapacity': 5000,
                        'onMarketStartDate': [2025, 1, 1], 'isFoldable': False})
    assert result['model_identifier'] == 'DEMO-ONE'
    assert result['eprel_reg_no'] == '9999999'
    assert result['energy_class'] == 'B'
    assert result['rated_battery_capacity'] == 5000
    assert result['on_market_start_date'] == '2025-01-01'
