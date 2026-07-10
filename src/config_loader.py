from __future__ import annotations

from pathlib import Path

import yaml

from src.models import AppConfig, PipelineSettings, ProjectConfig


def load_config(path: str | Path) -> ProjectConfig:
    config_path = Path(path)
    if not config_path.exists():
        raise FileNotFoundError(f"Configuration file not found: {config_path}")

    with config_path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}

    raw_apps = data.get("apps")
    if not isinstance(raw_apps, list) or not raw_apps:
        raise ValueError("Configuration must contain a non-empty 'apps' list")

    apps: list[AppConfig] = []
    required = {"app_id", "app_name", "vertical", "storefront", "expected_language", "enabled", "notes"}
    for index, raw_app in enumerate(raw_apps):
        if not isinstance(raw_app, dict):
            raise ValueError(f"apps[{index}] must be a mapping")
        missing = required - raw_app.keys()
        if missing:
            raise ValueError(f"apps[{index}] missing fields: {', '.join(sorted(missing))}")
        apps.append(
            AppConfig(
                app_id=str(raw_app["app_id"]),
                app_name=str(raw_app["app_name"]),
                vertical=str(raw_app["vertical"]),
                storefront=str(raw_app["storefront"]).lower(),
                expected_language=str(raw_app["expected_language"]).lower(),
                enabled=bool(raw_app["enabled"]),
                notes=str(raw_app["notes"]),
            )
        )

    raw_settings = data.get("settings") or {}
    settings = PipelineSettings(
        max_pages_per_app=int(raw_settings.get("max_pages_per_app", 2)),
        timeout_seconds=float(raw_settings.get("timeout_seconds", 15)),
        retry_count=int(raw_settings.get("retry_count", 3)),
        delay_seconds=float(raw_settings.get("delay_seconds", 1.0)),
    )
    if not 1 <= settings.max_pages_per_app <= 10:
        raise ValueError("max_pages_per_app must be between 1 and 10")
    if settings.timeout_seconds <= 0 or settings.retry_count < 1 or settings.delay_seconds < 0:
        raise ValueError("timeout, retry_count, and delay settings must be non-negative and usable")
    return ProjectConfig(apps=apps, settings=settings)
