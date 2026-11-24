# Live demo script (about 12 minutes)

Shows the whole loop: **documents change in Drive -> the helpdesk learns by itself -> answers cite the new facts**, plus the three model paths and the one controlled action.
All demo documents are fictional and say so in their footer. Regenerate them any time with `python scripts/make_demo_docs.py` (output: `data/demo_docs/`).

## Before the audience arrives

1. API and UI running; `.env` has the Drive lines from `docs/SETUP_DRIVE.md`, `DRIVE_POLL_ENABLED=true`, and a **short interval** for the demo: `DRIVE_SYNC_INTERVAL_SECONDS=60`
   (15 seconds is the lowest the settings accept; use 300 in normal life). Restart the API after changing `.env`.
2. The Drive folder contains only your real documents. **None of the four demo files is in it yet.**
3. Open two windows side by side: the chat, and the Drive folder.
4. Optional: a terminal on `GET /api/admin/drive/status` (header `X-Admin-Key`) to show `seconds_since_last_success` and per-file status.

## Act 1 - "The helpdesk does not know yet" (1 min)

Ask Model 2, one at a time. Each should honestly say the documents do not contain it (and cite nothing made up):

| Ask | Expected before |
|---|---|
| What are the library hours during the examination period? | not found in the documents |
| What is the last date to pay the second semester tuition fee? | not found |
| How do I get a bonafide certificate and what does it cost? | not found |
| Is there a guest lecture on AI this month? | not found |

Ask the first one to **Model 1** as well: it answers from general knowledge only, with no sources. That is the point of the comparison.

## Act 2 - "Drop the documents in Drive" (3 min)

1. Drag the four files from `data/demo_docs/step1_add/` into the Drive folder.
2. Wait one polling interval (or run `python scripts/sync_drive_once.py` for an instant sync, or `POST /api/admin/drive/sync`). Show the status: four new files, `indexed`.
3. Ask the same four questions again. Expected, with source chips pointing at Drive:
   - Library: Monday to Saturday 8:00 AM to 10:00 PM, Sundays and holidays 9:00 AM to 5:00 PM, 1 to 12 December 2026.
   - Fee: last date without fine **10 January 2027**, Rs 100 per day after it (max Rs 1,000), no hall ticket if unpaid by 25 January 2027.
   - Bonafide: apply at the Student Services counter or the portal, **Rs 50** (Rs 100 same-day), ready in 3 working days.
   - Guest lecture: **3 December 2026**, 2:00 to 3:30 PM, Seminar Hall, Main Block; register by 30 November 2026.
4. Point out: answers stream word by word, are formatted (bold, lists), and a follow-up works ("And for same-day issue?" -> Rs 100) because retrieval sees the conversation.

## Act 3 - "A document changes" (2 min)

1. In Drive, upload `data/demo_docs/step2_edit/Notice_Semester_Fee_Payment_Last_Date.docx` into the same folder. When Drive asks, choose **Replace existing file**
   (not "Keep both": that would create a second file with the same name and both would be indexed).
2. After the next poll, ask: *What is the last date to pay the second semester tuition fee?* Expected: **17 January 2027** (extended from 10 January), hall-ticket cutoff 31 January 2027.
   The old date is no longer offered as current. Show the status: that one file has a new version; the other three were skipped without being downloaded or embedded again.

## Act 4 - "A document is withdrawn" (1 min)

1. Move the guest-lecture notice to the Drive **trash**.
2. After the next poll, ask about the guest lecture again: no longer found, and no citation to it.

## Act 5 - Three model paths, honestly labelled (2 min)

- Same question to **Model 1** (no documents), **Model 2** (documents + hosted model), **Model 3** (documents + our fine-tuned endpoint).
- Model 3 shows a clear "not configured" error until the LoRA endpoint exists. It never silently answers with another model and calls it Model 3.
- Under each answer the UI shows the model label, the model id, **time to first word** and total latency. Tokens in/out and cost are in the API response (`usage`) and in the
  trace log for every turn; traces hold no message text.

## Act 6 - The one controlled action (2 min)

1. Use the synthetic applicant `CUAPP-DEMO-0001` with `aarav.demo@example.com` (SYNTHETIC data) to verify.
2. Ask: *Please resend my interview email.* Expected: the email goes to the address **in the database** (shown masked), simulated by the console provider, recorded once.
3. Ask again straight away: refused by the duplicate window, nothing is sent twice.
4. Try a wrong email: a uniform "could not verify" message, and the attempt counts against the rate limit.

## After the demo

- Delete the demo files from the Drive folder (trash them); the next poll removes them from the index.
- Set `DRIVE_SYNC_INTERVAL_SECONDS` back to 300.

## If something does not appear

| Symptom | Check |
|---|---|
| Nothing indexed after the interval | `GET /api/admin/drive/status`: `drive_ready` and `drive_error` say why (not shared, API off, wrong folder ID); is `DRIVE_POLL_ENABLED=true` and was the API restarted? |
| Edited file shows two entries | "Keep both" was chosen in Drive; trash the older copy |
| Old fee date still answered | the poll has not run yet: check `seconds_since_last_success`, or sync manually |
| Answer says "not found" for a fact that is in a file | the file is in a sub-folder (ignored) or its type is unsupported: run `python scripts/sync_drive_once.py --dry-run` |
