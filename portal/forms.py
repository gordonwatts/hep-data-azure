from __future__ import annotations

from django import forms

from portal.backend import list_backend_profiles


class JobSubmissionForm(forms.Form):
    original_prompt = forms.CharField(
        label="Prompt",
        widget=forms.Textarea(attrs={"rows": 6}),
    )
    backend_profile = forms.ChoiceField(choices=[])
    resolved_dataset = forms.CharField(
        label="Dataset",
        required=False,
        widget=forms.TextInput(attrs={"placeholder": "Optional override"}),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["backend_profile"].choices = [
            (profile.name, profile.label) for profile in list_backend_profiles()
        ]


class ApprovalDecisionForm(forms.Form):
    reason = forms.CharField(
        required=True,
        widget=forms.Textarea(attrs={"rows": 3}),
        label="Reason",
    )
