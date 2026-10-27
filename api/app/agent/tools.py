"""Tools the agent loop can call. One Tool per action; the loop dispatches by name.

A tool's `run` returns a plain dict the model reads back. Three outcomes are special:
- raise `Refusal(feedback)`: the tool checked the arguments and will not accept them. The model gets
  `{"error": feedback}` and tries again; the loop counts refusals per tool and escalates after `max_refusals`.
- raise `Stop(status, **result)`: the run is over (`done`, or `needs_review` with a `question`).
- any other exception: reported to the model as an error once, re-raised if it repeats on the same tool.

Checks belong inside the tool that commits the result, where the model cannot skip them.
"""
from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

ToolFn = Callable[..., dict[str, Any] | Awaitable[dict[str, Any]]]


class Refusal(Exception):
    """The tool rejects these arguments; the message is feedback for the model."""


class Stop(Exception):
    """The tool ends the run. status: 'done' | 'needs_review' | 'failed'."""

    def __init__(self, status: str, **result: Any):
        super().__init__(status)
        self.status = status
        self.result = result


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    schema: dict[str, Any]          # JSON schema of the arguments (Messages API `input_schema`)
    run: ToolFn                     # run(args: dict) or run(args, state) -> dict; sync or async
    commit: bool = False            # a commit tool's refusals count toward escalation

    def validate(self, args: dict[str, Any]) -> str | None:
        """Top-level check of required keys and primitive types; the message is for the model."""
        props = self.schema.get("properties", {})
        missing = [k for k in self.schema.get("required", []) if k not in args]
        if missing:
            return f"{self.name}: missing argument(s) {', '.join(missing)}; required: {', '.join(self.schema.get('required', []))}"
        unknown = [k for k in args if k not in props] if props else []
        if unknown:
            return f"{self.name}: unknown argument(s) {', '.join(unknown)}; allowed: {', '.join(props)}"
        kinds = {"integer": int, "number": (int, float), "string": str, "boolean": bool, "array": list, "object": dict}
        for k, v in args.items():
            want = props.get(k, {}).get("type")
            if want in kinds and not isinstance(v, kinds[want]) or (want == "integer" and isinstance(v, bool)):
                return f"{self.name}: argument {k!r} must be {want}, got {type(v).__name__} ({v!r})"
        return None

    def definition(self) -> dict[str, Any]:
        schema = {"type": "object", "additionalProperties": False, **self.schema}
        return {"name": self.name, "description": self.description, "input_schema": schema}


@dataclass
class ToolBox:
    tools: dict[str, Tool] = field(default_factory=dict)

    def add(self, tool: Tool) -> "ToolBox":
        self.tools[tool.name] = tool
        return self

    def tool(self, name: str, description: str, schema: dict[str, Any], *, commit: bool = False) -> Callable[[ToolFn], ToolFn]:
        def wrap(fn: ToolFn) -> ToolFn:
            self.add(Tool(name, description, schema, fn, commit))
            return fn
        return wrap

    def definitions(self) -> list[dict[str, Any]]:
        return [t.definition() for t in self.tools.values()]

    def __contains__(self, name: str) -> bool:
        return name in self.tools

    def __getitem__(self, name: str) -> Tool:
        return self.tools[name]

    async def call(self, name: str, args: dict[str, Any], state: Any = None) -> dict[str, Any]:
        tool = self.tools[name]
        n_params = len(inspect.signature(tool.run).parameters)
        out = tool.run(args, state) if n_params >= 2 else tool.run(args)
        if inspect.isawaitable(out):
            out = await out
        return out if isinstance(out, dict) else {"result": out}
