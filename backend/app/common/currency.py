"""The currencies documents may be written in.

Stored as the three-letter ISO code, always — every one of the 3,000-odd
imported documents holds "PKR", and a column that sometimes holds "$" and
sometimes "USD" cannot be grouped, filtered or totalled. The symbol is a
presentation detail, applied when an amount is printed.

`normalise` accepts what a person would actually type — "$", "usd", "Rs",
"€" — and returns the code to store, so the form can offer a free-text box
without the database paying for it.
"""

SYMBOLS = {
    "PKR": "PKR",   # no symbol: the reference documents print "PKR 1,234.00"
    "USD": "$",
    "EUR": "€",
    "GBP": "£",
    "AED": "AED",
    "CNY": "¥",
}

DEFAULT = "PKR"

# What someone might type for each code, beyond the code itself.
_ALIASES = {
    "$": "USD", "US$": "USD", "USD$": "USD", "DOLLAR": "USD", "DOLLARS": "USD",
    "€": "EUR", "EURO": "EUR", "EUROS": "EUR",
    "£": "GBP", "POUND": "GBP", "STERLING": "GBP",
    "RS": "PKR", "RS.": "PKR", "₨": "PKR", "RUPEE": "PKR", "RUPEES": "PKR",
    "PKR.": "PKR", "PK": "PKR",
    "DIRHAM": "AED", "¥": "CNY", "YUAN": "CNY", "RMB": "CNY",
}


def normalise(value: str | None) -> str:
    """The ISO code to store for whatever was typed. Unknown text is kept,
    upper-cased and trimmed to the column width, rather than rejected — a
    currency this list has not heard of is still a currency."""
    text = (value or "").strip()
    if not text:
        return DEFAULT
    upper = text.upper()
    if upper in SYMBOLS:
        return upper
    return _ALIASES.get(upper, upper[:10])


def symbol(code: str | None) -> str:
    """What to print in front of an amount."""
    code = (code or DEFAULT).strip().upper()
    return SYMBOLS.get(code, code)
