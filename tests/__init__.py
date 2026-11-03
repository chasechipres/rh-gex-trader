from rhgex import guardrails, paths

_load = guardrails.load


def template_guardrails(path=None) -> dict:
    """The template's limits, so hook tests never depend on anyone's private/guardrails.toml."""
    return _load(paths.TEMPLATE / "guardrails.toml")


from rhgex import paper  # noqa: E402

# Tests never see the owner's paper account: with it active, the hook would refuse every real order.
paper.PAPER = paths.ROOT / "tests" / "no-such-paper.json"
