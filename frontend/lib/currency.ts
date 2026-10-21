/**
 * The currencies a document can be written in.
 *
 * Documents store the three-letter code — every imported one holds "PKR" —
 * and the symbol is applied when an amount is shown. That way a total can
 * still be grouped and summed, while the form and the printed document read
 * the way people expect: "$ 1,234.00", "€ 950.00", "PKR 26,159.00".
 *
 * The list mirrors app/common/currency.py; the server normalises whatever is
 * typed ("$", "usd", "Rs") to the code before storing it.
 */
export interface CurrencyOption {
  code: string;
  symbol: string;
  name: string;
}

export const CURRENCIES: CurrencyOption[] = [
  { code: "PKR", symbol: "PKR", name: "Pakistan Rupee" },
  { code: "USD", symbol: "$", name: "US Dollar" },
  { code: "EUR", symbol: "€", name: "Euro" },
  { code: "GBP", symbol: "£", name: "Pound Sterling" },
  { code: "AED", symbol: "AED", name: "UAE Dirham" },
];

export const DEFAULT_CURRENCY = "PKR";

/**
 * Options for a picker: the list reads "$  USD — US Dollar", while the box
 * itself shows only "USD", which is what gets stored.
 */
export const currencyOptions = CURRENCIES.map((c) => ({
  value: c.code,
  short: c.code,
  label: c.symbol === c.code ? `${c.code} — ${c.name}` : `${c.symbol}  ${c.code} — ${c.name}`,
}));

/** What to print in front of an amount. An unknown code prints as itself. */
export function currencySymbol(code: string | null | undefined): string {
  const key = (code ?? DEFAULT_CURRENCY).trim().toUpperCase();
  return CURRENCIES.find((c) => c.code === key)?.symbol ?? key;
}

/** An amount with its currency, to two decimals. */
export function money(value: number, code: string | null | undefined = DEFAULT_CURRENCY): string {
  return `${currencySymbol(code)} ${value.toLocaleString("en-US", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`;
}
