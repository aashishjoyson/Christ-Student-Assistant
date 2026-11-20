# Licence and data notes

- **Code in this repository:** written for an academic project. Choose a licence before publishing (e.g. MIT) and add a `LICENSE` file.
- **Synthetic data** (`data/synthetic_applicants.csv`, `data/sample_docs/SYNTHETIC_*`, `data/eval/*`): fictional, created for testing. Uses the reserved `example.com` domain. Not Christ University information.
- **Real university documents:** may be copyrighted or internal. Keep them in Google Drive only; never commit or package them.
- **Base model for PEFT:** `Qwen/Qwen3-4B-Instruct-2507` is published under Apache-2.0 (verify on the model card at training time and keep its licence notice with any redistributed adapter).
- **Third-party services:** OpenAI, OpenRouter, Google Drive, Hugging Face, Modal and SMTP providers are used under their own terms; costs are the operator's responsibility.
- **Applicant data:** only synthetic records. Using real student data requires institutional authorisation and a privacy review.
