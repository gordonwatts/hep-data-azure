from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from django.core.exceptions import ImproperlyConfigured


@dataclass(frozen=True, slots=True)
class BackendProfile:
    name: str
    label: str
    default_dataset: str


@dataclass(frozen=True, slots=True)
class SubmissionInput:
    original_prompt: str
    resolved_dataset: str
    backend_profile: str


@dataclass(frozen=True, slots=True)
class ExamplePrompt:
    label: str
    prompt: str


BACKEND_PROFILES: dict[str, BackendProfile] = {
    "servicex_awkward": BackendProfile(
        name="servicex_awkward",
        label="ServiceX Awkward",
        default_dataset="servicex-awkward-default-dataset",
    ),
    "rdf": BackendProfile(
        name="rdf",
        label="RDF",
        default_dataset="rdf-default-dataset",
    ),
}

DEFAULT_BACKEND_PROFILE = "servicex_awkward"
EXAMPLE_PROMPTS_PATH = Path(__file__).resolve().parent / "data" / "example_prompts.json"


def list_backend_profiles() -> tuple[BackendProfile, ...]:
    return tuple(BACKEND_PROFILES.values())


def get_backend_profile(name: str) -> BackendProfile:
    try:
        return BACKEND_PROFILES[name]
    except KeyError as exc:  # pragma: no cover - exercised via validation paths later
        raise ImproperlyConfigured(f"Unknown backend profile: {name}") from exc


def default_backend_profile() -> BackendProfile:
    return get_backend_profile(DEFAULT_BACKEND_PROFILE)


def resolve_dataset(backend_profile: str, dataset: str | None) -> str:
    normalized_dataset = (dataset or "").strip()
    if normalized_dataset:
        return normalized_dataset
    return get_backend_profile(backend_profile).default_dataset


def normalize_submission_input(
    prompt: str,
    backend_profile: str,
    dataset: str | None = None,
) -> SubmissionInput:
    return SubmissionInput(
        original_prompt=prompt.strip(),
        resolved_dataset=resolve_dataset(backend_profile, dataset),
        backend_profile=backend_profile,
    )


def merge_prompt_and_dataset(prompt: str, dataset: str | None) -> str:
    normalized_prompt = prompt.strip()
    normalized_dataset = (dataset or "").strip()
    if not normalized_dataset:
        return normalized_prompt
    return f"{normalized_prompt}\n\nDataset: {normalized_dataset}"


@lru_cache(maxsize=1)
def load_example_prompts() -> tuple[ExamplePrompt, ...]:
    if not EXAMPLE_PROMPTS_PATH.exists():
        return ()

    raw: Any = json.loads(EXAMPLE_PROMPTS_PATH.read_text(encoding="utf-8"))
    prompts = []
    for item in raw:
        prompts.append(ExamplePrompt(label=item["label"], prompt=item["prompt"]))
    return tuple(prompts)
