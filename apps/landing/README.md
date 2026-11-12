# Fidero landing page (R0, EN-03)

One static page for the manual service: what a land check covers, the verdicts, how it works, what the report does not promise, and an order form. Bloc design (document 03, sections 6.1a and 6.1b).

Private preview: https://claude.ai/artifact/T4CNnYnyGbB4As3xuJ2oAo

## Before it goes live

1. In the script at the bottom of `index.html`, fill in `CONTACT.whatsapp` (international number, digits only) and `CONTACT.email`. The page then shows them and offers "Open in WhatsApp" and "Open in email".
2. Replace every `[TO VERIFY]`: the reply time, the company name and registration, and the data protection registration (EN-08).
3. Host it on any static host (for example GitHub Pages or Netlify) under Fidero's own domain.

## How the order form works

There is no server in R0. The form checks the answers and writes them into a message the visitor copies or opens in WhatsApp or email. Nothing is sent until the visitor sends it. Every request then goes into the Leads tab of `docs/operations/r0-tracker.xlsx`. A form service can replace this later without changing the page's look.

The sample report on the page is marked as a sample and is not a real plot.
