# Google Drive setup (Phase 3)

The app reads ONE folder, non-recursively, with the read-only scope `https://www.googleapis.com/auth/drive.readonly`.
Never commit credential files: keep them in `secrets/` (git-ignored).

## Option A (recommended): service account

Best for unattended polling: no browser login and no token expiry.

1. Google Cloud Console -> create (or pick) a project -> **APIs & Services -> Library** -> enable **Google Drive API**.
2. **IAM & Admin -> Service Accounts -> Create service account** (no roles needed).
3. Open it -> **Keys -> Add key -> JSON**. The browser downloads a JSON file (often called `keys.json` or `<project>-<id>.json`): **move it to `secrets/` and rename it `drive-service-account.json`**. It is a password: never paste its contents anywhere and never leave it outside `secrets/`.
4. Copy the service account email (`...@<project>.iam.gserviceaccount.com`).
5. In Google Drive, open your helpdesk folder -> **Share** -> add that email as **Viewer**.
6. Copy the folder ID from its URL (`https://drive.google.com/drive/folders/<FOLDER_ID>`).
7. `.env`:
   ```dotenv
   GOOGLE_DRIVE_FOLDER_ID=<FOLDER_ID>
   GOOGLE_DRIVE_AUTH_MODE=service_account
   GOOGLE_DRIVE_CREDENTIALS_FILE=./secrets/drive-service-account.json
   DRIVE_POLL_ENABLED=false   # start with manual sync; enable once it works
   ```
8. Run `python scripts/sync_drive_once.py` (Phase 3) and check `GET /api/admin/drive/status`.

If sharing with the service account is blocked (some university Workspace domains restrict external
sharing), use a personal Google account's Drive or Option B.

## Option B: OAuth (your own account)

1. Enable the Drive API (step A1). **APIs & Services -> OAuth consent screen**: user type External, add yourself as a test user.
2. **Credentials -> Create credentials -> OAuth client ID -> Desktop app**. Download JSON to `secrets/drive-oauth-client.json`.
3. `.env`:
   ```dotenv
   GOOGLE_DRIVE_AUTH_MODE=oauth
   GOOGLE_DRIVE_CREDENTIALS_FILE=./secrets/drive-oauth-client.json
   GOOGLE_DRIVE_TOKEN_FILE=./secrets/drive-token.json
   ```
4. Run `python scripts/drive_oauth_login.py` once; a browser opens; the token is saved to `secrets/drive-token.json`.

**Caveat:** while the consent screen is in "Testing" status, Google expires the authorization and refresh token
**7 days** after consent. Polling then fails with `invalid_grant` - re-run the login script. Publishing the app
to production removes the limit but may require verification for restricted scopes.

## Supported files

PDF, DOCX, XLSX, CSV, TXT, Markdown, Google Docs (exported to DOCX) and Google Sheets (exported to XLSX). Anything else is listed with status `unsupported`.
Files whose name starts with `SYNTHETIC_` are placeholders and are never indexed unless `LOCAL_DOCS_INCLUDE_SYNTHETIC=true`.
Shortcuts and sub-folders are ignored in v1. Trashed files are treated as deleted.

## Troubleshooting

| Symptom | Likely cause |
|---|---|
| 404 on the folder | Folder not shared with the service account, or wrong ID |
| 403 `insufficientPermissions` | Wrong scope or Drive API not enabled |
| `invalid_grant` after a week | OAuth Testing-mode token expiry |
| Google Doc indexed with no headings | Export fell back to plain text; check export MIME type |
