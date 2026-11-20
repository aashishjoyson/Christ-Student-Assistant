"""Pure business logic.

Rule: modules in this package use only the Python standard library.
No database, network, settings or framework imports. That keeps every
safety rule (routing, masking, email eligibility, chunking, prompts)
unit-testable in milliseconds and easy to explain in a viva.
"""
