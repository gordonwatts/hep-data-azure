from __future__ import annotations

import pytest
from django.core.exceptions import ImproperlyConfigured

from portal.backend import (
    BACKEND_PROFILES,
    DEFAULT_BACKEND_PROFILE,
    default_backend_profile,
    get_backend_profile,
    list_backend_profiles,
    load_example_prompts,
    merge_prompt_and_dataset,
    normalize_submission_input,
    resolve_dataset,
)


def test_backend_profile_listing_and_default():
    profiles = list_backend_profiles()

    assert [profile.name for profile in profiles] == list(BACKEND_PROFILES)
    assert default_backend_profile().name == DEFAULT_BACKEND_PROFILE
    assert get_backend_profile("rdf").label == "RDF"


def test_dataset_inference_and_prompt_merge():
    submission = normalize_submission_input("  Plot jets  ", "servicex_awkward")

    assert submission.original_prompt == "Plot jets"
    assert submission.resolved_dataset == "servicex-awkward-default-dataset"
    assert resolve_dataset("rdf", "  custom-dataset  ") == "custom-dataset"
    assert merge_prompt_and_dataset("Plot jets", "custom-dataset") == (
        "Plot jets\n\nDataset: custom-dataset"
    )


def test_example_prompts_load():
    prompts = load_example_prompts()

    assert len(prompts) == 2
    assert prompts[0].label == "Make a histogram"
    assert prompts[1].prompt == "Compare signal and background yields across all bins."


def test_unknown_backend_profile_is_rejected():
    with pytest.raises(ImproperlyConfigured):
        get_backend_profile("unknown")
