"""Shared test helpers."""


def as_if_real(value):
    """Replace the placeholder text of a synthetic example, the way a reader replaces it with real sources."""
    if isinstance(value, dict):
        return {key: as_if_real(item) for key, item in value.items()}
    if isinstance(value, list):
        return [as_if_real(item) for item in value]
    if isinstance(value, str):
        return value.replace("example.invalid", "sources.test").replace("SYNTHETIC", "STAND-IN")
    return value
