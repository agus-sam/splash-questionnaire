# Google Sheets setup

The app writes to a Google Sheet through a **service account**. This is a robot account with its own e-mail address.
You share the Sheet with it, like with a colleague.

## 1. Create the Sheet

1. Go to sheets.google.com and create a blank spreadsheet. Name it `SPLASH Questionnaire and Simulation data`.
2. Copy the ID from the address bar: `https://docs.google.com/spreadsheets/d/`**`THIS_PART`**`/edit`.
3. Leave it empty. The app creates the tabs `submissions`, `answers`, `results`, `contacts` and their headers on first start.

## 2. Create the service account

1. Open console.cloud.google.com and create a project (for example `splash-survey`).
2. Search for **Google Sheets API** and click **Enable**.
3. Go to **IAM and admin, Service accounts, Create service account**. Name it `splash-survey`. Skip the optional role steps.
4. Open the new account, tab **Keys, Add key, Create new key, JSON**. A file downloads. Keep it private.

Google may also ask you to enable the **Google Drive API** for some operations. If the app reports a permission error on the first
start, enable it the same way.

## 3. Share the Sheet with the service account

Open the JSON file. Copy the value of `client_email` (it looks like `splash-survey@...iam.gserviceaccount.com`).
In the Sheet click **Share**, paste that address, give it the role **Editor**, and untick "notify".

## 4. Paste the secrets

Copy `.streamlit/secrets.toml.example`. Fill in `spreadsheet_id` and copy each field from the JSON file into `[storage.service_account]`.
Paste the result into Streamlit Community Cloud under **App settings, Secrets** (or save it as `.streamlit/secrets.toml` for local runs).

The `private_key` must keep its `\n` line breaks exactly as in the JSON file.

## 5. How the data looks

| Tab | One row per | Content |
|---|---|---|
| `submissions` | save event | resume code, time, stage, language, versions, full answers as JSON |
| `answers` | answer and save event | `question_id`, `value` (long format) |
| `results` | result value and save event | KPI name and value (long format) |
| `contacts` | final save with consent | name, contact, method, consent, summary request |

Rows are only ever appended. A respondent has several stages (`step1`, `step2`, `core`, `results`, `final`). To analyse, take the latest
row per resume code. The admin page and its Excel export already do this and give you one wide row per respondent.

Text that starts with `=`, `+`, `-` or `@` is stored with a leading apostrophe so it can never run as a spreadsheet formula.

## 6. Limits and good practice

* Google allows about 60 write requests per minute per user. This is plenty for a survey of this size. The app saves after each questionnaire step and again on results and final. Each save is up to four append calls (submissions, answers, results, contacts), so a respondent causes about 15 to 25 write requests. About three respondents per minute saturate the quota. The app retries with backoff; for an invitation wave, send in batches.
* Do not edit or sort the tabs by hand while the survey is open. Copy the data to another file for analysis.
* Keep a weekly copy: **File, Download, Microsoft Excel**.
* Delete test rows before the real survey.
* Anyone with the Sheet link and access can read personal data. Share it with named people only.
