"""Application-level exceptions safe to render in any presentation layer."""


class DomainError(Exception):
    """Base error for a business-rule or requested-resource failure."""


class AccessDeniedError(DomainError):
    """Raised when an actor attempts to read data outside their scope."""


class NotFoundError(DomainError):
    """Raised when an expected business resource does not exist."""


class ValidationError(DomainError):
    """Raised for a business input validation failure."""
