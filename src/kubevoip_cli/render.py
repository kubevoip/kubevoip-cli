from __future__ import annotations

import json
from typing import Any

import yaml


def yaml_dump(value: Any) -> str:
    return yaml.safe_dump(value, sort_keys=False)


def json_dump(value: Any) -> str:
    return json.dumps(value, indent=2, sort_keys=False) + "\n"


def output(value: Any, *, fmt: str) -> str:
    if fmt == "json":
        return json_dump(value)
    return yaml_dump(value)


def table(headers: list[str], rows: list[list[str]]) -> str:
    widths = [len(header) for header in headers]
    for row in rows:
        for index, cell in enumerate(row):
            widths[index] = max(widths[index], len(cell))
    lines = ["  ".join(header.ljust(widths[index]) for index, header in enumerate(headers))]
    lines.append("  ".join("-" * width for width in widths))
    for row in rows:
        lines.append("  ".join(cell.ljust(widths[index]) for index, cell in enumerate(row)))
    return "\n".join(lines) + "\n"

