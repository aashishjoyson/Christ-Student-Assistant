# Email setup

## Default: simulated (no setup)

```dotenv
EMAIL_PROVIDER=console
EMAIL_SEND_ENABLED=false
```
A resend writes the full message to `storage/outbox/sim-<id>.txt`, records a `simulated` event in
`notification_events`, and the UI says "Demo mode: the email was simulated and not actually delivered."
This is the right mode for development, tests and demos, and today it is the only mode that works.

## Real sending (Phase 5, opt-in): NOT BUILT

**Status (2026-11-25):** the SMTP sender (`app/services/email/smtp.py`) has not been written, so no message reaches any inbox, Gmail included; the only output is the simulated file described above.
The settings below are the design. Today `EMAIL_PROVIDER=smtp` with `EMAIL_SEND_ENABLED=true` makes the API **refuse to start** ("SMTP sending is implemented in Phase 5"); keep `EMAIL_PROVIDER=console` and `EMAIL_SEND_ENABLED=false`.

Real sending would need **all** of:
```dotenv
EMAIL_PROVIDER=smtp
EMAIL_SEND_ENABLED=true
EMAIL_RECIPIENT_ALLOWLIST=@example.com,your.test.inbox@gmail.com
EMAIL_FROM=helpdesk-demo@yourdomain.example
SMTP_HOST=...
SMTP_PORT=587
SMTP_USERNAME=...
SMTP_PASSWORD=        # set only in your local .env
SMTP_USE_STARTTLS=true
```
The allowlist is a hard guard: recipients that do not match are `not_eligible` and nothing is sent. The app
refuses to start with SMTP enabled and an empty allowlist.

### Recommended for demos: an SMTP sandbox

A sandbox inbox (for example Mailtrap's testing inbox) accepts SMTP and shows the message in a web UI without
delivering it to anyone. Use its SMTP credentials above and put the seeded `@example.com` domain in the allowlist.

### Delivering to your own inbox

1. Edit one row of `data/synthetic_applicants.csv`: set `registered_email` to your test address. Re-seed.
2. Add that exact address to `EMAIL_RECIPIENT_ALLOWLIST`.
3. Use an SMTP account you control (for Gmail this requires 2-step verification and an app password;
   check Google's current policy).

## What "sent" means

`sent` = the SMTP server accepted the message (it returned success). It does not prove delivery to the inbox,
so the UI never says "delivered". Every attempt is in `notification_events` with status, provider message ID,
timestamps and any error.
