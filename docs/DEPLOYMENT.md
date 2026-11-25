# Deployment

You need a GitHub account, a Google account and about one hour. No university server.

## 1. Put the repository on GitHub

1. On github.com click **New repository**. Name it `splash-questionnaire-simulation`. Choose **Private** (you can make it public later).
2. Do not add a README or licence there. The repository already has them.
3. On the new empty repository page click **uploading an existing file** and drag in the *contents* of this folder
   (not the folder itself), or use git:

```bash
git remote add origin https://github.com/<your-user>/splash-questionnaire-simulation.git
git push -u origin main
```

Check that `.streamlit/secrets.toml` and `*.db` files are **not** in the repository (the `.gitignore` prevents it).

## 2. Create the Google Sheet and the service account

Follow [GOOGLE_SHEETS_SETUP.md](GOOGLE_SHEETS_SETUP.md). You end with a spreadsheet ID and a JSON key.

## 3. Deploy on Streamlit Community Cloud

1. Go to share.streamlit.io and sign in with GitHub. Allow access to the repository (private repositories need this).
2. **Create app**, choose the repository, branch `main`, main file `app.py`.
3. Open **Advanced settings**. Pick Python 3.12 or 3.13. Paste your secrets (format in `.streamlit/secrets.toml.example`).
4. Deploy. The first start takes a few minutes.
5. Choose a short, neutral app URL, for example `splash-questionnaire-simulation`.

The free tier lets an app sleep after a period without visitors. The first visitor then waits a moment for it to wake up.
Open the link yourself a few minutes before you send invitations.

## 4. Test with the real storage

1. Open the app, click through a test submission with your own name, finish it.
2. In the Sheet you should see rows in `submissions`, `answers`, `results` (and `contacts` if you gave consent).
3. Open `https://<your-app>.streamlit.app/?admin=1`, enter the admin password, check the tables and the Excel export.
4. Take the resume code from the last page and use "Schon begonnen?" on the welcome page to reload the submission.
5. Delete your test rows in the Sheet before the real survey.

If the Sheet connection fails, the app does **not** fall back to local files (the disk of the server is temporary and
would hold personal data). It shows a red banner, respondents can still see their results, but nothing is saved and the
final step does not close. Always run step 4 before you send invitations.

## 5. Before the survey goes out (checklist)

| Item | Where | Done when |
|---|---|---|
| Replace illustrative parameters by SPLASH technology and economics data | `data/parameters.yaml` | no `illustrative` rows that matter remain, `meta.status: validated` |
| Confirm the curtailment signal definition and the 2026 data after 22 November | `data/real/curtailment_hourly_T5_T6.csv`, `data/splash/PROVENANCE.csv` | `python scripts/validate_data.py` is clean; provenance filled |
| Fill `zones.csv` with the real postal-code mapping | `data/real/zones.csv` | pools map to the right zone |
| Complete privacy notice, imprint, DPO name | `data/privacy_notice.md` | DPO approved, no `[...]` placeholders left |
| Ethics vote if required | your faculty | decision filed |
| Validate the model for 2 to 3 pools you know | with SPLASH WP1 | specific heat use and results plausible to you |
| Have a native speaker read the German texts | `splash_app/i18n.py`, `data/questions.yaml` | approved |
| Pilot with 3 to 5 operators | think-aloud | confusing items fixed |
| Set a strong admin password | secrets | not shared in chat or email |
| Generate personal links (optional) | `data/pool_prefill.csv` | random tokens, expiry date set (ISO format `YYYY-MM-DD`). The file is git-ignored; on Community Cloud commit it to a **private** deployment repository or leave the feature off |

## 6. Updating the app

Edit a file on GitHub (or push), and Streamlit redeploys within a minute. Submissions store the questionnaire, parameter and app
version, so you can always tell which version a respondent saw. Change `meta.version` in `data/questions.yaml` and
`data/parameters.yaml` whenever you change content.

## 7. Where the data lives

* **Answers:** your Google Sheet. Share it only with the project team. Choose an EU data region if your Google Workspace allows it.
* **App server:** Streamlit Community Cloud. Check with your data protection officer where it runs and whether this is acceptable for your
  data. The app itself stores nothing on the server, and it loads no external fonts or trackers.
* If the DPO says no to Community Cloud, the same code runs on a university or institute VM with
  `streamlit run app.py` (or in a Docker container) with no changes.
