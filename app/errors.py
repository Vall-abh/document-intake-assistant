"""Application errors. Each maps to a stable HTTP status and machine-readable code."""


class AppError(Exception):
    status_code = 500
    code = "internal_error"

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class SessionNotFound(AppError):
    status_code = 404
    code = "session_not_found"


class LLMConfigError(AppError):
    status_code = 503
    code = "llm_not_configured"


class LLMUnavailable(AppError):
    status_code = 502
    code = "llm_unavailable"


class MalformedModelOutput(AppError):
    status_code = 502
    code = "malformed_model_output"
