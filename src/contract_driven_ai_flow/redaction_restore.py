"""A browser mask preserves an existing value; it cannot silently replace that value."""
from .models import ProjectSpec
from .privacy import sanitize_project


def restore_project(candidate: ProjectSpec, current: ProjectSpec) -> ProjectSpec:
    before = current.model_dump(mode="json")
    displayed = sanitize_project(current)

    def restore(value, original, safe):
        if original != safe and value == safe:
            return original
        if isinstance(value, dict) and isinstance(original, dict) and isinstance(safe, dict):
            return {k: restore(v, original[k], safe[k]) if k in original and k in safe else v for k, v in value.items()}
        if isinstance(value, list) and isinstance(original, list) and isinstance(safe, list):
            lookup = {v["id"]: (v, s) for v, s in zip(original, safe) if isinstance(v, dict) and "id" in v}
            result = []
            for index, v in enumerate(value):
                if isinstance(v, dict) and "id" in v:
                    pair = lookup.get(v["id"])
                else:
                    pair = (original[index], safe[index]) if index < len(original) and index < len(safe) else None
                result.append(restore(v, *pair) if pair else v)
            return result
        return value
    return ProjectSpec.model_validate(restore(candidate.model_dump(mode="json"), before, displayed))
