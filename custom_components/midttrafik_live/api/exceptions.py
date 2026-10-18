"""Exceptions raised by the Midttrafik Live client."""


class MidttrafikLiveError(Exception):
    """Base error for the Midttrafik Live client."""


class MidttrafikLiveConnectionError(MidttrafikLiveError):
    """Network problem or timeout talking to the API."""


class MidttrafikLiveApiError(MidttrafikLiveError):
    """The API answered with an error status or an unexpected payload."""

    def __init__(self, status: int, errors: object | None = None) -> None:
        super().__init__(f"API returned status {status}: {errors}")
        self.status = status
        self.errors = errors
