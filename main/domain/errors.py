class AppError(RuntimeError):
    """Base application error."""


class NotFoundError(AppError):
    pass


class ProviderError(AppError):
    pass


class ValidationError(AppError):
    pass
