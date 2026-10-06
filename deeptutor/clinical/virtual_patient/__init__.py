"""Virtual patient MVP (plan WP6): deterministic consultation state machine.

Truth is owned by the engine in this package; LLM involvement is limited to
phrasing patient replies later (plan §5.2). Sessions are event-sourced and
fully replayable. Dynamic vital-sign evolution and mass-casualty constraints
stay out of scope (WP9).
"""
