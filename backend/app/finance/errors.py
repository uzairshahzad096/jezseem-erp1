"""
Finance errors, and turning database refusals into readable ones.

Finance services raise `FinanceError` rather than HTTPException because the
posting engine will be called from sales, procurement and inventory code,
which is not always inside a request. main.py maps it to a 400 (or the given
status) with the message as the detail.

The database triggers in migration 0008 raise messages written for the
user, e.g. "Period Jul 2026 is CLOSED and does not accept postings."
`db_guard` passes those through unchanged and translates the constraint
names that a person could otherwise not interpret.
"""

from contextlib import contextmanager

from sqlalchemy.exc import DBAPIError, IntegrityError


class FinanceError(Exception):
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


#: Constraint name -> what to tell the user.
CONSTRAINT_MESSAGES = {
    "uq_journal_number": "That journal number is already used in this financial year.",
    "uq_journal_document_event": "This document has already been posted to the ledger.",
    "uq_account_code": "Another account already uses that code.",
    "uq_account_group_code": "Another account group already uses that code.",
    "uq_cost_center_code": "Another cost centre already uses that code.",
    "uq_period_number": "That period already exists for this financial year.",
    "uq_opening_batch_live": "An opening balance batch is already posted for this year and branch.",
    "uq_opening_batch_number": "That opening batch number is already used.",
    "uq_document_series_type": "That document type already has a numbering series.",
    "ck_line_non_negative": "Debit and credit amounts cannot be negative.",
    "ck_line_base_non_negative": "Debit and credit amounts cannot be negative.",
    "ck_line_one_side": "Each line needs either a debit or a credit, not both and not neither.",
    "ck_line_base_one_side": "Each line needs either a debit or a credit, not both and not neither.",
    "ck_line_one_party": "A line can name a customer or a supplier, not both.",
}


def _message(error: DBAPIError) -> str | None:
    orig = getattr(error, "orig", None)
    diag = getattr(orig, "diag", None)
    sqlstate = getattr(orig, "sqlstate", None)
    constraint = getattr(diag, "constraint_name", None)
    if constraint and constraint in CONSTRAINT_MESSAGES:
        return CONSTRAINT_MESSAGES[constraint]
    # P0001 = raise_exception from one of the finance triggers.
    if sqlstate == "P0001":
        return getattr(diag, "message_primary", None) or str(orig)
    if isinstance(error, IntegrityError):
        return f"The change conflicts with existing data ({constraint or sqlstate})."
    return None


@contextmanager
def db_guard(db):
    """Run a flush/commit, turning a trigger or constraint refusal into a
    FinanceError. The session is rolled back so it stays usable."""
    try:
        yield
    except DBAPIError as error:
        message = _message(error)
        db.rollback()
        if message is None:
            raise
        raise FinanceError(message) from error


def translate(error: DBAPIError) -> FinanceError | None:
    """For callers that catch the error themselves."""
    message = _message(error)
    return FinanceError(message) if message else None
