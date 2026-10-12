"""Decimal, long-only multi-asset accounting. No broker connectivity."""

from decimal import Decimal, ROUND_DOWN

from .live_schemas import PortfolioDecision

FEE = Decimal('0.0001')
SLIPPAGE = Decimal('0.0002')
LOT = Decimal('0.000001')
ZERO = Decimal(0)


def decimal(value):
    return Decimal(str(value))


def new_book(initial_cash, *, start_date):
    return {'cash': str(initial_cash), 'holdings': {}, 'receivables': {},
            'applied_actions': {}, 'start_date': start_date}


def equity(book, quotes):
    return (decimal(book['cash'])
            + sum((decimal(qty) * decimal(quotes[symbol]['price']) for symbol, qty in book['holdings'].items()), ZERO)
            + sum((decimal(item['amount']) for item in book['receivables'].values()), ZERO))


def apply_actions(book, actions, today):
    """Credit only shares held before ex-date; unsettled dividends are not cash."""
    changed = []
    for action in actions:
        if action['date'] <= book['start_date']:
            continue
        action_id = action['id']
        fingerprint = str(action.get('factor', action.get('amount')))
        previous = book['applied_actions'].get(action_id)
        if previous is not None and previous != fingerprint:
            raise ValueError('A previously applied corporate action was revised; review is required')
        if previous is None:
            quantity = decimal(book['holdings'].get(action['symbol'], '0'))
            if action['kind'] == 'split':
                if quantity:
                    book['holdings'][action['symbol']] = str(quantity * decimal(action['factor']))
            elif quantity:
                book['receivables'][action_id] = {
                    'amount': str(quantity * decimal(action['amount'])), 'payment_date': action['payment_date'],
                }
            book['applied_actions'][action_id] = fingerprint
            if quantity:
                changed.append(action)
        elif action['kind'] == 'dividend' and action_id in book['receivables'] and action['payment_date']:
            book['receivables'][action_id]['payment_date'] = action['payment_date']
    for action_id, item in list(book['receivables'].items()):
        if item['payment_date'] and item['payment_date'] <= today:
            book['cash'] = str(decimal(book['cash']) + decimal(item['amount']))
            del book['receivables'][action_id]
    return changed


def weights(decision: PortfolioDecision, symbols, max_allocation):
    if any(item.symbol not in symbols for item in decision.targets):
        raise ValueError('A decision selected a ticker outside this study')
    result = {symbol: ZERO for symbol in symbols}
    result.update({item.symbol: decimal(item.weight) for item in decision.targets})
    total, cap = sum(result.values(), ZERO), decimal(max_allocation)
    if total > cap:
        result = {symbol: weight * cap / total for symbol, weight in result.items()}
    return result


def rebalance(book, quotes, target_weights, *, threshold):
    """Sell first, then buy with available cash, including fees and slippage."""
    value = equity(book, quotes)
    if value <= ZERO:
        return []
    targets = {symbol: (value * weight / decimal(quotes[symbol]['price'])).quantize(LOT, rounding=ROUND_DOWN)
               for symbol, weight in target_weights.items()}
    fills = []
    for side in ('sell', 'buy'):
        for symbol in sorted(targets):
            owned = decimal(book['holdings'].get(symbol, '0'))
            difference = targets[symbol] - owned
            if (side == 'buy' and difference <= ZERO) or (side == 'sell' and difference >= ZERO):
                continue
            reference = decimal(quotes[symbol]['price'])
            if abs(difference) * reference / value < decimal(threshold):
                continue
            price = reference * (1 + SLIPPAGE if side == 'buy' else 1 - SLIPPAGE)
            cash_before = decimal(book['cash'])
            quantity = abs(difference)
            if side == 'buy':
                affordable = (cash_before / (price * (1 + FEE))).quantize(LOT, rounding=ROUND_DOWN)
                quantity = min(quantity, affordable)
            else:
                quantity = min(quantity, owned)
            if quantity <= ZERO:
                continue
            notional = quantity * price
            fee = notional * FEE
            book['cash'] = str(cash_before - notional - fee if side == 'buy' else cash_before + notional - fee)
            after = owned + quantity if side == 'buy' else owned - quantity
            if after:
                book['holdings'][symbol] = str(after)
            else:
                book['holdings'].pop(symbol, None)
            fills.append({'symbol': symbol, 'side': side, 'quantity': float(quantity), 'price': float(price),
                          'reference_price': float(reference), 'fee': float(fee), 'quote_as_of': quotes[symbol]['as_of'],
                          'cash_before': str(cash_before), 'cash_after': book['cash'],
                          'quantity_before': str(owned), 'quantity_after': str(after)})
    return fills
