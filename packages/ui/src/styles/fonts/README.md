# Site Studio fonts

Inter, Manrope, DM Sans, Nunito, Lora and Playfair Display are bundled locally
from Google Fonts. Each family includes Latin and Latin Extended WOFF2 subsets
with upright weights 400–700 (Manrope 400–800: its variable file covers the
whole range and the studio and product styles set headings at 800), including
Polish characters. Font files total
approximately 436 KiB on disk; the browser fetches only the selected family
and required subsets. `font-display: swap` keeps text visible while loading.

`sources.json` records source URLs, SHA-256 hashes and the download date.
Each family has its original OFL license alongside the unmodified font files.
Source catalogue: https://github.com/google/fonts
Google Fonts FAQ: https://fonts.google.com/faq

No runtime Google request or arbitrary tenant-provided font URL is needed.
Both the public renderer and editor use the same CSS assets.
