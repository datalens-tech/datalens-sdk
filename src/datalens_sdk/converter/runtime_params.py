from datalens_sdk.domain.runtime_params import RuntimeParams


def runtime_params_payload(params: RuntimeParams) -> dict[str, str | list[str]]:
    """Copy runtime values to JSON containers without URL encoding or name policy."""
    return {key: value if isinstance(value, str) else list(value) for key, value in params.items()}
