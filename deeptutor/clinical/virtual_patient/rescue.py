"""Rescue scenario layer (plan WP9, first increment).

Deterministic overlay on the virtual patient engine: a *simulated clock*
advanced by per-action time costs, vital-sign evolution from checkpoint
rules and intervention effects, a finite resource pool and an evacuation
deadline.  Wall-clock time is never used — the clock is the sum of logged
action costs, so sessions stay fully replayable (hard constraint #5).

Config lives in the case's ``content.patient_script.rescue`` block:

    {
      "time_budget_minutes": 60,
      "action_costs": {"ask_question": 3, "wait": 10, ...},
      "deterioration": [
        {"after_minutes": 15, "vitals": {"oxygenSaturation": -4},
         "symptoms": ["意识模糊"]}
      ],
      "interventions": [
        {"action": "order_exam", "match": "氧疗",
         "vitals": {"oxygenSaturation": 6},
         "consumes": {"oxygen": 1}, "repeatable": false}
      ],
      "resources": {"oxygen": 4},
      "evac_eta_minutes": 40
    }

Deltas are integers added to the initial vitals; interventions trigger when
the action type matches and ``match`` (case-insensitive substring) appears
in the payload text.  Nothing here involves an LLM.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

DEFAULT_ACTION_COSTS: dict[str, int] = {
    "begin": 2,
    "ask_question": 3,
    "order_exam": 5,
    "advance_phase": 2,
    "reassess": 3,
    "wait": 10,
    "submit_disposition": 5,
}


class RescueConfigError(ValueError):
    pass


@dataclass(frozen=True)
class DeteriorationRule:
    after_minutes: int
    vitals: dict[str, int]
    symptoms: tuple[str, ...] = ()


@dataclass(frozen=True)
class InterventionRule:
    action: str
    match: str
    vitals: dict[str, int]
    consumes: dict[str, int]
    repeatable: bool = False


@dataclass(frozen=True)
class RescueConfig:
    time_budget_minutes: int
    action_costs: dict[str, int]
    deterioration: tuple[DeteriorationRule, ...]
    interventions: tuple[InterventionRule, ...]
    resources: dict[str, int]
    evac_eta_minutes: int

    def action_cost(self, action_type: str) -> int:
        return self.action_costs.get(action_type, DEFAULT_ACTION_COSTS.get(action_type, 2))

    def content_hash_input(self) -> dict[str, Any]:
        return {
            "time_budget_minutes": self.time_budget_minutes,
            "action_costs": self.action_costs,
            "deterioration": [
                {"after_minutes": d.after_minutes, "vitals": d.vitals, "symptoms": list(d.symptoms)}
                for d in self.deterioration
            ],
            "interventions": [
                {
                    "action": i.action,
                    "match": i.match,
                    "vitals": i.vitals,
                    "consumes": i.consumes,
                    "repeatable": i.repeatable,
                }
                for i in self.interventions
            ],
            "resources": self.resources,
            "evac_eta_minutes": self.evac_eta_minutes,
        }


def parse_rescue_config(raw: Any) -> RescueConfig | None:
    """Validate the ``rescue`` block; ``None`` when absent.  Raises
    :class:`RescueConfigError` on malformed blocks."""
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise RescueConfigError("rescue must be an object")
    budget = raw.get("time_budget_minutes")
    if not isinstance(budget, int) or budget <= 0:
        raise RescueConfigError("rescue.time_budget_minutes must be a positive integer")
    evac = raw.get("evac_eta_minutes")
    if not isinstance(evac, int) or evac <= 0:
        raise RescueConfigError("rescue.evac_eta_minutes must be a positive integer")

    costs_raw = raw.get("action_costs", {})
    if not isinstance(costs_raw, dict):
        raise RescueConfigError("rescue.action_costs must be an object")
    action_costs: dict[str, int] = dict(DEFAULT_ACTION_COSTS)
    for key, value in costs_raw.items():
        if not isinstance(value, int) or value < 0:
            raise RescueConfigError(f"rescue.action_costs['{key}'] must be a non-negative integer")
        action_costs[str(key)] = value

    def _int_map(value: Any, label: str) -> dict[str, int]:
        if not isinstance(value, dict):
            raise RescueConfigError(f"rescue.{label} must be an object of integer deltas")
        out: dict[str, int] = {}
        for k, v in value.items():
            if not isinstance(v, int):
                raise RescueConfigError(f"rescue.{label}['{k}'] must be an integer")
            out[str(k)] = v
        return out

    deterioration: list[DeteriorationRule] = []
    for i, item in enumerate(raw.get("deterioration", []) or []):
        if not isinstance(item, dict) or not isinstance(item.get("after_minutes"), int):
            raise RescueConfigError(f"rescue.deterioration[{i}] needs integer after_minutes")
        deterioration.append(
            DeteriorationRule(
                after_minutes=item["after_minutes"],
                vitals=_int_map(item.get("vitals", {}), f"deterioration[{i}].vitals"),
                symptoms=tuple(str(s) for s in item.get("symptoms", []) or []),
            )
        )

    interventions: list[InterventionRule] = []
    for i, item in enumerate(raw.get("interventions", []) or []):
        if not isinstance(item, dict) or not item.get("action"):
            raise RescueConfigError(f"rescue.interventions[{i}] needs an action type")
        interventions.append(
            InterventionRule(
                action=str(item["action"]),
                match=str(item.get("match", "")),
                vitals=_int_map(item.get("vitals", {}), f"interventions[{i}].vitals"),
                consumes=_int_map(item.get("consumes", {}), f"interventions[{i}].consumes"),
                repeatable=bool(item.get("repeatable", False)),
            )
        )

    resources = _int_map(raw.get("resources", {}), "resources")
    return RescueConfig(
        time_budget_minutes=budget,
        action_costs=action_costs,
        deterioration=tuple(deterioration),
        interventions=tuple(interventions),
        resources=resources,
        evac_eta_minutes=evac,
    )


def apply_rescue_step(
    config: RescueConfig,
    *,
    elapsed_minutes: int,
    vitals: dict[str, int],
    symptoms: tuple[str, ...],
    resources_used: dict[str, int],
    interventions_taken: tuple[str, ...],
    action_type: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    """Pure transition for one action under rescue rules.

    Returns the next-step fields: ``elapsed_minutes``, ``vitals``,
    ``symptoms``, ``resources_used``, ``interventions_taken`` and a
    ``rescue_events`` list describing what fired (time advanced, rules
    triggered, rejections).  Raises nothing — rejections are reported as
    rescue events the caller turns into errors.
    """
    cost = config.action_cost(action_type)
    if action_type == "wait":
        minutes = payload.get("minutes")
        if isinstance(minutes, int) and minutes > 0:
            cost = minutes

    new_elapsed = elapsed_minutes + cost
    if new_elapsed > config.time_budget_minutes:
        return {
            "error": f"time budget exceeded: {new_elapsed}/{config.time_budget_minutes} minutes",
            "elapsed_minutes": elapsed_minutes,
            "vitals": vitals,
            "symptoms": symptoms,
            "resources_used": resources_used,
            "interventions_taken": interventions_taken,
            "rescue_events": [],
        }

    new_vitals = dict(vitals)
    new_symptoms = symptoms
    new_used = dict(resources_used)
    new_taken = interventions_taken
    rescue_events: list[dict[str, Any]] = [{"event": "time", "elapsed": new_elapsed}]

    # 1) intervention effects of the action itself (before deterioration
    #    fires on the new clock — treatment precedes the next checkpoint).
    for rule in config.interventions:
        if rule.action != action_type:
            continue
        if rule.match and rule.match.lower() not in json_text(payload):
            continue
        marker = f"{rule.action}:{rule.match}"
        if marker in new_taken:
            continue
        shortfalls = {
            key: need - (config.resources.get(key, 0) - new_used.get(key, 0))
            for key, need in rule.consumes.items()
            if config.resources.get(key, 0) - new_used.get(key, 0) < need
        }
        if shortfalls:
            rescue_events.append({"event": "resource_shortage", "missing": shortfalls})
            continue
        for key, delta in rule.vitals.items():
            new_vitals[key] = new_vitals.get(key, 0) + delta
        for key, amount in rule.consumes.items():
            new_used[key] = new_used.get(key, 0) + amount
        new_taken = tuple(dict.fromkeys((*new_taken, f"{rule.action}:{rule.match}")))
        rescue_events.append({"event": "intervention", "rule": f"{rule.action}:{rule.match}"})

    # 2) deterioration checkpoints newly passed on the new clock.
    for rule in config.deterioration:
        if elapsed_minutes < rule.after_minutes <= new_elapsed:
            for key, delta in rule.vitals.items():
                new_vitals[key] = new_vitals.get(key, 0) + delta
            if rule.symptoms:
                new_symptoms = tuple(dict.fromkeys((*new_symptoms, *rule.symptoms)))
            rescue_events.append({"event": "deterioration", "after_minutes": rule.after_minutes})

    return {
        "error": None,
        "elapsed_minutes": new_elapsed,
        "vitals": new_vitals,
        "symptoms": new_symptoms,
        "resources_used": new_used,
        "interventions_taken": new_taken,
        "rescue_events": rescue_events,
    }


def json_text(payload: dict[str, Any]) -> str:
    return " ".join(str(v) for v in payload.values()).lower()


def rescue_outcome(
    config: RescueConfig,
    *,
    elapsed_minutes: int,
    vitals: dict[str, int],
    disposition_correct: bool | None,
) -> dict[str, Any]:
    """Deterministic outcome metrics reported when a rescue session ends."""
    return {
        "disposition_correct": disposition_correct,
        "elapsed_minutes": elapsed_minutes,
        "time_budget_minutes": config.time_budget_minutes,
        "time_remaining_minutes": config.time_budget_minutes - elapsed_minutes,
        "evac_in_time": elapsed_minutes <= config.evac_eta_minutes,
        "evac_eta_minutes": config.evac_eta_minutes,
        "final_vitals": dict(vitals),
    }
