# Licence and data notes

- **Code in this repository:** written for an academic project. Choose a licence before publishing (e.g. MIT) and add a `LICENSE` file.
- **Synthetic data** (`data/synthetic_applicants.csv`, `data/sample_docs/SYNTHETIC_*`, `data/eval/*`): fictional, created for testing. Uses the reserved `example.com` domain. Not Christ University information.
- **Real university documents:** may be copyrighted or internal. Keep them in Google Drive only; never commit or package them.
- **Base model for PEFT:** `Qwen/Qwen3-4B-Instruct-2507` is published under Apache-2.0 (verify on the model card at training time and keep its licence notice with any redistributed adapter).
- **Third-party services:** OpenAI, OpenRouter, Google Drive, Hugging Face, Modal and SMTP providers are used under their own terms; costs are the operator's responsibility.
- **Applicant data:** only synthetic records. Using real student data requires institutional authorisation and a privacy review.
- **Images on the demo homepage** (`frontend/public/home/*.jpg`): generated with an AI image tool by the project owner and optimised; they are illustrative scenes, **not photographs of the real campus**, and the page that shows them is labelled "Demo backdrop". Originals are kept locally in the git-ignored `data/private/home-originals/`. Replace them with licensed or official photos for any public use.
- **Christ University crest** (`frontend/public/christ-logo.png`): copied unchanged from the owner's `aura-ai` repository. The emblem and the university name are the university's marks: confirm you may use them before publishing this repository or the demo outside the academic project.
- **Website FAQ text** (indexed from `data/sample_docs/`, fetched from the university's public FAQ page on 2026-11-24): the university's own content, kept out of git (ignored). Do not republish it.
- **Evidently** (`evidently`, Apache-2.0) is an optional evaluation dependency (`backend/requirements-eval.txt`); `openpyxl` (MIT), `pypdf` (BSD) and `python-docx` (MIT) parse documents.
