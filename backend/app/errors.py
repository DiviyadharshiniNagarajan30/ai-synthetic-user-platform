"""Application errors rendered as consistent JSON: {"detail": "...", "code": "..."}."""


class AppError(Exception):
    status_code = 500
    code = "internal_error"

    def __init__(self, detail: str, *, code: str | None = None, extra: dict | None = None):
        super().__init__(detail)
        self.detail = detail
        if code:
            self.code = code
        self.extra = extra or {}


class NotFound(AppError):
    status_code = 404
    code = "not_found"


class Conflict(AppError):
    status_code = 409
    code = "conflict"


class BadRequest(AppError):
    status_code = 400
    code = "bad_request"


class ServiceUnavailable(AppError):
    status_code = 503
    code = "service_unavailable"


class BadGateway(AppError):
    status_code = 502
    code = "bad_ai_output"
