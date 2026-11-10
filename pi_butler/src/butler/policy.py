"""Fail-closed target resolution and finite operation catalog. No API forwarding."""
import hashlib
import json
import math
import re

ENTITY = re.compile(r"[a-z0-9_]+\.[a-z0-9_]+\Z")
SELECTORS = {"entity_ids", "domains", "label_ids"}


class Rejected(ValueError):
    pass


def strings(value, name, maximum=256):
    if not isinstance(value, list) or not 0 < len(value) <= maximum:
        raise Rejected(f"{name} must be a nonempty list (maximum {maximum})")
    if any(not isinstance(v, str) or not v or len(v) > 255 for v in value):
        raise Rejected(f"Invalid {name}")
    return value


def validate_policy(policy):
    if not isinstance(policy, dict) or set(policy) - {"enabled", "allow", "deny_entity_ids"}:
        raise Rejected("Invalid policy fields")
    if type(policy.get("enabled")) is not bool or not isinstance(policy.get("allow"), list):
        raise Rejected("Invalid policy")
    if len(policy['allow']) > 256:
        raise Rejected('Too many allow rules')
    for rule in policy["allow"]:
        if not isinstance(rule, dict) or set(rule) - (SELECTORS | {"capability"}):
            raise Rejected("Invalid allow rule")
        if rule.get("capability") not in {"control", "trigger_automation"}:
            raise Rejected("Unknown capability")
        active = {k: v for k, v in rule.items() if k in SELECTORS and v != []}
        if not active:
            raise Rejected("Allow rule needs at least one selector")
        for k, v in active.items():
            strings(v, k)
            if k == "entity_ids" and any(not ENTITY.fullmatch(x) for x in v):
                raise Rejected("Invalid entity ID")
            if k == "domains" and any(not re.fullmatch('[a-z0-9_]+', x) for x in v):
                raise Rejected("Invalid domain")
    deny = policy.get("deny_entity_ids", [])
    if not isinstance(deny, list):
        raise Rejected("deny_entity_ids must be a list")
    if deny:
        strings(deny, "deny_entity_ids")
        if any(not ENTITY.fullmatch(x) for x in deny):
            raise Rejected("Invalid denied entity ID")
    return policy


class Policy:
    def __init__(self, config):
        self.config = validate_policy(config)
        self.version = hashlib.sha256(json.dumps(config, sort_keys=True).encode()).hexdigest()[:16]

    def permits(self, entity, capability, registry):
        if not self.config["enabled"] or entity in self.config.get("deny_entity_ids", []):
            return False
        labels = registry.get(entity, {}).get("labels", [])
        for rule in self.config["allow"]:
            if rule["capability"] != capability:
                continue
            if rule.get("entity_ids") and entity not in rule["entity_ids"]:
                continue
            if rule.get("domains") and entity.split('.')[0] not in rule["domains"]:
                continue
            if rule.get("label_ids") and not set(labels).intersection(rule["label_ids"]):
                continue
            return True
        return False

    def resolve(self, target, states, registry):
        if not isinstance(target, dict) or not target or set(target) - SELECTORS:
            raise Rejected("Use entity_ids, domains or directly assigned label_ids targets")
        known = {s['entity_id'] for s in states}
        resolved = set()
        for category, values in target.items():
            strings(values, category)
            for value in values:
                if category == "entity_ids":
                    matches = {value} if ENTITY.fullmatch(value) and value in known else set()
                elif category == "domains":
                    matches = {e for e in known if e.split('.')[0] == value}
                else:
                    matches = {e for e in known if value in registry.get(e, {}).get("labels", [])}
                if not matches:
                    raise Rejected(f"Unresolved target: {category}={value}")
                resolved.update(matches)
        if not resolved or len(resolved) > 256:
            raise Rejected("Target must resolve to 1–256 active entities")
        return sorted(resolved)

    def authorize(self, domain, action, target, data, states, registry):
        capability, cleaned = operation(domain, action, data)
        entities = self.resolve(target, states, registry)
        if any(e.split('.')[0] != domain for e in entities):
            raise Rejected("Every target must belong to the action domain")
        if any(not self.permits(e, capability, registry) for e in entities):
            raise Rejected("At least one target is denied; no actions executed")
        if domain == "calendar":
            by_id = {s['entity_id']: s for s in states}
            if any(not (int(by_id[e].get('attributes', {}).get('supported_features', 0)) & 1) for e in entities):
                raise Rejected("Calendar does not advertise CREATE_EVENT")
        return entities, cleaned


def number(value, low, high):
    return type(value) in (int, float) and math.isfinite(value) and low <= value <= high


def operation(domain, action, data):
    if not isinstance(data, dict):
        raise Rejected("Action data must be an object")
    allowed = set()
    capability = "control"
    if domain in {"switch", "input_boolean"} and action in {"turn_on", "turn_off", "toggle"}:
        pass
    elif domain == "light" and action in {"turn_on", "turn_off", "toggle"}:
        allowed = {"transition", "flash"}
        if action != "turn_off":
            allowed |= {"brightness", "brightness_pct", "brightness_step", "brightness_step_pct",
                        "rgb_color", "rgbw_color", "rgbww_color", "hs_color", "xy_color",
                        "color_temp_kelvin", "color_name", "effect", "white"}
    elif domain == "automation" and action in {"turn_on", "turn_off", "toggle", "trigger"}:
        if action == "trigger":
            capability = "trigger_automation"
            allowed = {"skip_condition"}
        elif action == "turn_off":
            allowed = {"stop_actions"}
    elif domain == "calendar" and action == "create_event":
        allowed = {"summary", "description", "location", "start_date_time", "end_date_time", "start_date", "end_date"}
        if not isinstance(data.get("summary"), str) or not data["summary"]:
            raise Rejected("Calendar summary required")
        date = {"start_date", "end_date"}
        time = {"start_date_time", "end_date_time"}
        if not ((date <= data.keys() and not time.intersection(data)) or
                (time <= data.keys() and not date.intersection(data))):
            raise Rejected("Provide one complete calendar date or datetime pair")
        from datetime import date as Date, datetime
        try:
            if date <= data.keys():
                start, end = Date.fromisoformat(data['start_date']), Date.fromisoformat(data['end_date'])
            else:
                start, end = datetime.fromisoformat(data['start_date_time']), datetime.fromisoformat(data['end_date_time'])
            if end <= start:
                raise ValueError()
        except (ValueError, TypeError):
            raise Rejected("Invalid calendar interval") from None
    else:
        raise Rejected("Unsupported operation; arbitrary HA actions are not exposed")
    if set(data) - allowed:
        raise Rejected("Unsupported action fields (embedded targets are forbidden)")
    ranges = {"transition": (0, 300), "brightness": (0, 255), "brightness_pct": (0, 100),
              "brightness_step": (-255, 255), "brightness_step_pct": (-100, 100), "color_temp_kelvin": (1000, 40000)}
    vectors = {"rgb_color": (255,)*3, "rgbw_color": (255,)*4, "rgbww_color": (255,)*5,
               "hs_color": (360, 100), "xy_color": (1, 1)}
    for key, value in data.items():
        valid = True
        if key in ranges:
            valid = number(value, *ranges[key])
        elif key in vectors:
            valid = isinstance(value, list) and len(value) == len(vectors[key]) and all(number(v, 0, m) for v, m in zip(value, vectors[key]))
        elif key in {"skip_condition", "stop_actions", "white"}:
            valid = type(value) is bool
        elif key == 'flash':
            valid = value in ('short', 'long')
        else:
            valid = isinstance(value, str) and len(value) <= 4096
        if not valid:
            raise Rejected(f"Invalid action field: {key}")
    return capability, dict(data)
