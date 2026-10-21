const ONES = ["", "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight", "Nine", "Ten", "Eleven", "Twelve",
  "Thirteen", "Fourteen", "Fifteen", "Sixteen", "Seventeen", "Eighteen", "Nineteen"];
const TENS = ["", "", "Twenty", "Thirty", "Forty", "Fifty", "Sixty", "Seventy", "Eighty", "Ninety"];

/** Whole number in words, as the printed documents write it (app/documents/import_po_pdf._words). */
export function numberInWords(n: number): string {
  if (n === 0) return "Zero";
  const parts: string[] = [];
  for (const [value, name] of [[1e9, "Billion"], [1e6, "Million"], [1000, "Thousand"], [1, ""]] as const) {
    const chunk = Math.floor(n / value);
    n %= value;
    if (!chunk) continue;
    const words: string[] = [];
    const hundreds = Math.floor(chunk / 100), rest = chunk % 100;
    if (hundreds) words.push(`${ONES[hundreds]} Hundred`);
    if (rest) words.push(rest < 20 ? ONES[rest] : `${TENS[Math.floor(rest / 10)]} ${ONES[rest % 10]}`.trim());
    parts.push(words.join(" ") + (name ? ` ${name}` : ""));
  }
  return parts.join(" ");
}

/** "Rupees Twelve Thousand and Paisa Fifty Only", from an amount in paisa. */
export function rupeesInWords(paisa: number): string {
  const whole = Math.floor(paisa / 100), cents = paisa % 100;
  return `Rupees ${numberInWords(whole)}${cents ? ` and Paisa ${numberInWords(cents)}` : ""} Only`;
}
