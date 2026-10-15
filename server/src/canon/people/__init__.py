"""Who owns what and who knows what, from evidence, and how many people could answer for each area."""


def recompute(graph, *, today: str | None = None) -> dict[str, dict[str, int]]:
    """Expertise first, then the bus factor built on it. Safe to run again: both replace what they wrote before."""
    from canon.people import bus_factor, expertise

    return {"expertise": expertise.compute(graph, today=today), "bus_factor": bus_factor.compute(graph)}
