# Document artwork

Two optional image files. The PDF renderer picks them up automatically when
they are present and falls back to plain type when they are not, so the
application runs either way — but the printed documents only match the
supplied Quotation once both are here.

| File | What it is | Where it prints |
|---|---|---|
| `logo.png` | The JEZSEEM TRADERS wordmark **including** the green tagline underneath it | Top-left of every document, above the address |
| `signature.png` | The authorised signature together with the round company stamp | Below the Remarks box, above Bank Details |

## Saving them

Save the two images you already have into this folder under exactly those
names. PNG with a transparent background is best; JPEG works too, but keep the
`.png` filename or the renderer will not find it.

Sizing is automatic — each is scaled to fit its box while keeping its
proportions, so any reasonably sized export works:

- `logo.png` fits a 86 × 20 mm box. Around 900 px wide is plenty.
- `signature.png` fits a 58 × 26 mm box. Around 650 px wide is plenty.

Trim surrounding whitespace before saving. The renderer cannot tell padding
baked into the image from the artwork itself, so a generous white margin makes
the logo look small and off-centre on the page.

## Why these are not in the repository

They are company property, not code, and they carry an authorised signature.
Keeping them out of version control means a copy of the source tree is not also
a copy of the signature. If this folder is ever committed, add the two
filenames to `.gitignore` first.
