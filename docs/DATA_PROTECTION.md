# Data protection notes for the data protection officer

This is a technical description to speed up the review. It is not legal advice.

## What the app does and does not do

* Collects answers about a pool and its energy use, calculated results, and optional contact details.
* The respondent must tick a consent box before starting. A second consent covers the contact details.
* Contact details are written to a separate tab and are excluded from the standard Excel export.
* No external fonts, scripts, analytics, trackers or third-party API calls. All assets are served by the app. Charts are drawn in the browser by
  the bundled Plotly library.
* Streamlit usage statistics are switched off (`.streamlit/config.toml`).
* A resume code (8 random characters) lets a respondent reload their answers. The code is not derived from any personal data.
* Optional personal links use random tokens with an expiry date. They pre-fill only pool name, city, postal code, pool type and operator type.
* Formula injection is neutralised in the Sheet.
* The admin area is behind a password (constant-time comparison). Set the password only in the secrets.

## Points to decide before launch

| Topic | Decision needed |
|---|---|
| Controller, address, imprint | fill in `data/privacy_notice.md` |
| Legal basis | consent (Art. 6(1)(a)). Confirm whether public-interest research (Art. 6(1)(e) with the state data protection act) applies instead |
| Hosting of the app | Streamlit Community Cloud. Confirm location and the need for a processing agreement |
| Hosting of the data | Google Sheets. Confirm EU region, processing agreement, and access list |
| Retention | deletion date for contact details, rules for anonymised data |
| Deletion on request | process: respondent sends the resume code, project team deletes the rows in all four tabs |
| Minimum group size | no publication of results for fewer than N pools (set N) |
| Ethics vote | required or not at your faculty |
| Pool names | a pool name can identify an operator. Decide whether names are pseudonymised before analysis |
| Free-text fields | may hold personal data (comments, effects of past changes). Treat them as personal data in the analysis |

## Data minimisation in the questionnaire

Everything except the consent, pool basics and the willingness and flexibility items is optional. The calculation works with defaults
and says so. Contact details are optional and need their own consent.
