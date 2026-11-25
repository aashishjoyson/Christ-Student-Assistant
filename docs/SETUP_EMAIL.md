# Email setup

Two modes. **Simulated** is the default and needs no setup. **Real sending** over SMTP is opt-in and was built on 2026-11-25.

## Mode 1: simulated (default, no setup)

```dotenv
EMAIL_PROVIDER=console
EMAIL_SEND_ENABLED=false
```
A resend writes the full message to `storage/outbox/sim-<id>.txt`, records a `simulated` event in
`notification_events`, and the chat says "Demo mode: the email was simulated and not actually delivered."
This is the right mode for development, tests and rehearsals. Nothing reaches an inbox.

## Mode 2: real sending over SMTP

**Status:** built and tested against a pretend mail server (`backend/tests/fakes_smtp.py`; 61 tests, including a full run through the real graph and
database). No test contacts a real mail server, so **the first real send is yours**: `scripts/send_test_email.py` below does exactly that and
tells you why if it fails.

**What the code guarantees** (each point is pinned by a test):

| Rule | Where |
|---|---|
| The recipient is read from the database inside `send_interview_email`; text in the chat can never change it | `graph/nodes/applicant.py` |
| The recipient must be in `EMAIL_RECIPIENT_ALLOWLIST` (an address or `@domain`), checked **before** anything is reserved or any connection is opened | `check_resend_eligibility` |
| One send per cooldown window (reserve-then-send with a UNIQUE key); `sent` is recorded only after the server accepted the message; a failure is audited and frees the window | `db/repositories/notifications.py` |
| The connection is always encrypted and the certificate and host name are verified (TLS 1.2 or newer). A server that does not offer STARTTLS is **not** used in plain text. Plain SMTP is allowed only to `localhost` | `services/email/smtp.py` |
| Exactly one plain recipient address; a line break in the subject or address is refused (no Bcc injection) | `services/email/smtp.py` |
| One attempt and a hard timeout (`SMTP_TIMEOUT_SECONDS`, default 15 s); no retry inside the provider | `services/email/smtp.py` |
| A failure reason is one short line with the password and the addresses removed; message text is never logged | `services/email/smtp.py` |
| With real sending on, a missing allowlist, a placeholder `EMAIL_FROM` or unusable SMTP settings **stop the application at start-up** with a message that says what to fix | `services/email/factory.py` |

### Step by step with Gmail

Google documents it like this: app passwords only work on accounts with **2-Step Verification** turned on
(Google Account Help, "Sign in with app passwords"), and `smtp.gmail.com` accepts TLS on ports 465 and 587
(Google Workspace Admin Help, "Send email from a printer, scanner, or app"). Google also says app passwords are "not recommended and unnecessary in
most cases"; for a program that must log in to SMTP with a password, it is what is needed. A university (Workspace) account may have app passwords
disabled by its administrator: use a personal `@gmail.com` address for the demo.

1. Google Account > Security > turn on **2-Step Verification**.
2. In the account search box type **App passwords**, create one called `helpdesk`, copy the 16 letters (the spaces are not part of it; the app removes them).
3. Put this in `.env` (never in a file that is committed, never in chat):
   ```dotenv
   EMAIL_PROVIDER=smtp
   EMAIL_SEND_ENABLED=true
   EMAIL_FROM=you@gmail.com
   EMAIL_RECIPIENT_ALLOWLIST=you@gmail.com
   SMTP_HOST=smtp.gmail.com
   SMTP_PORT=587
   SMTP_USERNAME=you@gmail.com
   SMTP_PASSWORD=<the 16 letters>
   SMTP_USE_STARTTLS=true
   DEMO_APPLICANT_EMAIL=you@gmail.com
   ```
   Gmail sends as the account you log in with, so keep `EMAIL_FROM` equal to `SMTP_USERNAME`. Port 465 (implicit TLS) also works: set `SMTP_PORT=465`.
4. Give the demo applicant your address, in place (nothing is dropped): `python scripts/set_demo_email.py`
   (A fresh `python scripts/seed_demo_db.py --yes` does the same but also drops the Drive indexing history and the feedback.)
5. Check the settings **before** starting the app: `python scripts/send_test_email.py --to you@gmail.com`.
   It prints each step with its time (connect, starttls, login, send) and ends with `ACCEPTED` or `NOT SENT: <reason>`.
6. Restart the API. `GET /api/health` now shows `"email": {"provider": "smtp", "send_enabled": true}`.
7. In the chat, verify as `CUAPP-DEMO-0001` with **your** address (the "registered email"), then say *I have not received my interview email.*
   The answer says it was re-sent to the masked address (`y*****u@gmail.com`); look in the inbox, and in spam the first time.
   A second request inside 15 minutes is refused by the cooldown; any other applicant is refused because their address is not in the allowlist.

Other SMTP servers (a sandbox such as Mailtrap, your own domain) work the same way with their host, port, username and password. A sandbox shows the
message in a web page without delivering it to anyone, which is the safest way to rehearse.

### What "sent" means

`sent` = the SMTP server **accepted** the message (it returned success). It does not prove the message reached an inbox, so the product says "I've re-sent
your interview details ... please also check your spam folder" and never "delivered". Every attempt is a row in `notification_events` with its status,
the server's Message-ID, the times and a short reason when it failed; the live dashboard (`#/flow`) shows the same steps as they happen.

### When it does not work

| What you see | Usual cause | Fix |
|---|---|---|
| `SMTP 535 ... Username and Password not accepted` | the account password was used, 2-Step Verification is off, or the app password was copied wrongly | create an app password and paste it again |
| `SMTP 534 ... Application-specific password required` | 2-Step Verification is on and a normal password was used | use the app password |
| `STARTTLS extension not supported by server` | the port is one that does not do STARTTLS | use port 587 with `SMTP_USE_STARTTLS=true`, or port 465 |
| `timed out after 15 s`, `ConnectionRefusedError`, `gaierror` | outbound port 587/465 is blocked (some campus and public networks) | try the other port or another network |
| `SSLCertVerificationError` | an antivirus or proxy re-signs HTTPS/TLS traffic with a certificate Python does not trust | add its root certificate to the Windows store, or test on another network |
| the chat says sending is restricted to approved test recipients | the registered address is not in `EMAIL_RECIPIENT_ALLOWLIST` | add it (and use `set_demo_email.py` to put it on the demo applicant) |
| the API will not start: `EMAIL_SEND_ENABLED=true requires ...` | a safety guard; the message names the missing setting | fix `.env` or switch back to `EMAIL_PROVIDER=console` |

To go back to simulated mode at any time: `EMAIL_PROVIDER=console` (or `EMAIL_SEND_ENABLED=false`) and restart.
