from rhgex import guardrails, paths

_load = guardrails.load


def template_guardrails(path=None) -> dict:
    """The template's limits, so hook tests never depend on anyone's private/guardrails.toml."""
    return _load(paths.TEMPLATE / "guardrails.toml")
