"""Capture limits shared by native adapters and external agent processes."""
from dataclasses import dataclass


@dataclass(frozen=True)
class CapturePolicy:
    level: str = "summary"
    max_control_details: int = 512
    max_preview_cells: int = 1024
    max_stat_elements: int = 4096
    publish_interval_ms: int = 100
    max_queue_events: int = 2048
    max_queue_bytes: int = 8 * 1024 * 1024
    max_artifact_bytes: int = 64 * 1024 * 1024
    max_run_bytes: int = 256 * 1024 * 1024
    sensitive_fields: tuple[str, ...] = ("email", "password", "secret", "api_key", "access_token", "authorization")
    full_targets: tuple[str, ...] = ()

    def __post_init__(self):
        if self.level not in ("metadata", "sample", "summary", "full"):
            raise ValueError("Unknown scientific capture level")
        limits = {"max_control_details":512, "max_preview_cells": 4096, "max_stat_elements": 65536,
                  "max_queue_events": 10000, "max_queue_bytes": 64 * 1024 * 1024,
                  "max_artifact_bytes": 64 * 1024 * 1024, "max_run_bytes": 256 * 1024 * 1024,
                  "publish_interval_ms": 10000}
        for key, maximum in limits.items():
            number = getattr(self, key)
            if type(number) is not int or not 1 <= number <= maximum:
                raise ValueError(f"{key} must be between 1 and {maximum}")
        if len(self.sensitive_fields) > 128 or any(type(f) is not str or len(f) > 256 for f in self.sensitive_fields):
            raise ValueError("Sensitive field configuration is too large")
        if len(self.full_targets) > 4096 or any(type(key) is not str or len(key) > 4096 for key in self.full_targets):
            raise ValueError('Targeted full-capture selectors exceed budget')
