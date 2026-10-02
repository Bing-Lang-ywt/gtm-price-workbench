"""Evaluate supplied rules and samples without a database or notification sender."""
from decimal import Decimal
import math
from app.services.price_preflight import SUPPORTED_PRICE_TYPES


def _number(value, field):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f'{field} must be a finite nonnegative number')
    try:
        valid = math.isfinite(value) and value >= 0
    except OverflowError:
        valid = False
    if not valid:
        raise ValueError(f'{field} must be a finite nonnegative number')
    return Decimal(str(value))


def _identifier(value, field):
    if value is None:
        return ''
    if not isinstance(value, str) or len(value) > 200:
        raise ValueError(f'{field} must be a string of at most 200 characters')
    return value


def preview_rules(rules, samples):
    if not isinstance(rules, list) or not 1 <= len(rules) <= 50:
        raise ValueError('Provide 1 to 50 rules')
    if not isinstance(samples, list) or not 1 <= len(samples) <= 100:
        raise ValueError('Provide 1 to 100 samples')
    validated_rules = []
    for rule in rules:
        if not isinstance(rule, dict):
            raise ValueError('Each rule must be an object')
        condition = rule.get('condition_type')
        if condition not in ('below', 'above', 'delta_pct', 'new_entry'):
            raise ValueError('Unsupported condition_type')
        threshold = rule.get('threshold')
        if condition == 'new_entry':
            if threshold is not None:
                raise ValueError('new_entry threshold must be null')
        else:
            threshold = _number(threshold, 'threshold')
        scope = rule.get('scope_type', 'all')
        if scope not in ('all', 'sku', 'model', 'channel', 'segment'):
            raise ValueError('Unsupported scope_type')
        scope_id = _identifier(rule.get('scope_id'), 'scope_id')
        if scope == 'segment' and scope_id:
            raise ValueError('Named segments require catalog data and are not supported offline')
        price_type = rule.get('price_type')
        if price_type is not None and price_type not in ('unlocked', 'contract_monthly', 'subsidy_down_payment'):
            raise ValueError('Unsupported rule price_type')
        active = rule.get('is_active', True)
        if not isinstance(active, bool):
            raise ValueError('is_active must be boolean')
        bindings = {key: _identifier(rule.get(key), key) for key in ('sku_id', 'model_id', 'channel_id')}
        validated_rules.append((condition, threshold, scope, scope_id, price_type, active, bindings))
    validated_samples = []
    for sample in samples:
        if not isinstance(sample, dict):
            raise ValueError('Each sample must be an object')
        identifiers = {key: _identifier(sample.get(key), key) for key in ('sku_id', 'model_id', 'channel_id')}
        if not all(identifiers.values()):
            raise ValueError('Sample sku_id, model_id and channel_id are required')
        price_type = sample.get('price_type')
        if not isinstance(price_type, str) or price_type not in SUPPORTED_PRICE_TYPES:
            raise ValueError('Unsupported sample price_type')
        amount = _number(sample.get('amount_eur'), 'amount_eur')
        previous = sample.get('previous_amount_eur')
        previous = _number(previous, 'previous_amount_eur') if previous is not None else None
        new_entry = sample.get('is_new_entry', False)
        if not isinstance(new_entry, bool) or (new_entry and previous is not None):
            raise ValueError('is_new_entry must be boolean; a new entry cannot have a previous price')
        validated_samples.append((identifiers, price_type, amount, previous, new_entry))
    results, seen = [], {}
    matched_count = 0
    for sample_index, (ids, ptype, amount, previous, new_entry) in enumerate(validated_samples):
        key = (tuple(ids.values()), ptype, amount, previous, new_entry)
        duplicate_of = seen.get(key)
        seen.setdefault(key, sample_index)
        evaluations = []
        for rule_index, (cond, threshold, scope, scope_id, rule_type, active, bindings) in enumerate(validated_rules):
            matched = False
            if duplicate_of is not None:
                reason = 'duplicate_sample'
            elif not active:
                reason = 'inactive_rule'
            elif rule_type is not None and rule_type != ptype:
                reason = 'price_type_mismatch'
            elif any(value and ids[field] != value for field, value in bindings.items()):
                reason = 'scope_mismatch'
            elif not any(bindings.values()) and scope in ('sku', 'model', 'channel') and ids[scope+'_id'] != scope_id:
                reason = 'scope_mismatch'
            elif cond == 'delta_pct' and (previous is None or previous == 0):
                reason = 'no_positive_previous_price'
            else:
                if cond == 'below':
                    matched = amount < threshold
                elif cond == 'above':
                    matched = amount > threshold
                elif cond == 'delta_pct':
                    matched = abs(amount-previous) / previous * 100 >= threshold
                else:
                    matched = new_entry
                reason = 'condition_matched' if matched else 'condition_not_met'
            matched_count += int(matched)
            evaluations.append({'rule_index': rule_index, 'matched': matched, 'reason': reason})
        results.append({'sample_index': sample_index, 'duplicate_of': duplicate_of, 'evaluations': evaluations})
    return {'matched_count': matched_count, 'results': results}
