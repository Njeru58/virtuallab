import re

from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import UserCreationForm
from django.core.exceptions import ValidationError
from django.utils.translation import gettext as _

from .models import ExperimentDraft, ExperimentReport, Programme

User = get_user_model()

User = get_user_model()


class LabLoginForm(forms.Form):
    registration_number = forms.CharField(
        label="Registration Number",
        widget=forms.TextInput(attrs={
            "class": "form-control",
            "placeholder": "e.g. SC209/1087/2022"
        })
    )
    password = forms.CharField(
        widget=forms.PasswordInput(attrs={
            "class": "form-control",
            "placeholder": "••••••••"
        })
    )

    def clean(self, *args, **kwargs):
        self.user = None
        reg_no = self.cleaned_data.get("registration_number")
        password = self.cleaned_data.get("password")

        if reg_no and password:
            reg_no = reg_no.strip()
            # Resolve user by custom registration number or fallback username
            user = (
                User.objects.filter(registration_number__iexact=reg_no).first()
                or User.objects.filter(username__iexact=reg_no).first()
            )

            if not user or not user.check_password(password):
                raise forms.ValidationError("Invalid registration number or password.")

            if not user.is_active:
                raise forms.ValidationError("This account is inactive. Please verify your email.")

            self.user = user

        return super().clean(*args, **kwargs)


class LabRegistrationForm(UserCreationForm):
    email = forms.EmailField(
        required=True,
        widget=forms.EmailInput(attrs={"class": "form-control"})
    )

    class Meta:
        model = User
        fields = [
            "username",
            "registration_number",
            "programme",
            "year_group",
            "email",
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        for field in self.fields.values():
            field.widget.attrs.update({"class": "form-control"})

        self.fields["username"].help_text = "Format: SURNAME Firstname"
        self.fields["registration_number"].help_text = "Format: e.g. SC209/1087/2022"

        # Dynamically bind queryset to the exact model CustomUser.programme references
        if "programme" in self.fields:
            ProgrammeModel = User._meta.get_field("programme").remote_field.model
            self.fields["programme"].queryset = ProgrammeModel.objects.filter(is_active=True)

    def clean_password1(self):
        password = self.cleaned_data.get("password1")
        if len(password) < 8:
            raise ValidationError("Password must be at least 8 characters long.")
        if not re.search(r"\d", password):
            raise ValidationError("Password must contain at least one number.")
        if not re.search(r"[A-Z]", password):
            raise ValidationError("Password must contain at least one uppercase letter.")
        return password

    def clean_password2(self):
        p1 = self.cleaned_data.get("password1")
        p2 = self.cleaned_data.get("password2")
        if p1 and p2 and p1 != p2:
            raise ValidationError("Passwords do not match.")
        return p2

    def clean_username(self):
        username = self.cleaned_data.get("username", "").strip()
        parts = username.split()

        if len(parts) < 2:
            raise forms.ValidationError("Enter at least SURNAME and Firstname.")

        surname = parts[0]
        if not surname.isupper():
            raise forms.ValidationError("Surname must be in UPPERCASE.")

        return username

    def clean_registration_number(self):
        reg_no = self.cleaned_data.get("registration_number", "").strip()

        if not reg_no:
            return reg_no

        if "/" not in reg_no:
            raise forms.ValidationError("Enter a valid registration number (e.g. SC209/1087/2022).")

        return reg_no


class StudentProfileForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ["username", "email", "avatar", "bio", "year_group"]
        widgets = {
            "bio": forms.Textarea(attrs={"rows": 3, "class": "form-control"}),
            "year_group": forms.Select(attrs={"class": "form-control"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["username"].widget.attrs.update({"readonly": "readonly", "class": "form-control"})
        self.fields["email"].widget.attrs.update({"readonly": "readonly", "class": "form-control"})
        if "bio" in self.fields:
            self.fields["bio"].widget.attrs.update({"class": "form-control"})
        if "avatar" in self.fields:
            self.fields["avatar"].widget.attrs.update({"class": "form-control"})



class ExperimentReportForm(forms.ModelForm):
    class Meta:
        model = ExperimentReport
        fields = [
            'group_members', 'objective', 'theory', 'apparatus_scope',
            'procedure', 'results', 'data_analysis', 'discussion',
            'conclusion', 'references', 'data', 'graph_x_values', 
            'graph_y_values', 'report_file'
        ]

        widgets = {
            'group_members': forms.Textarea(attrs={'class': 'form-control', 'rows': 2}),
            'objective': forms.Textarea(attrs={'class': 'form-control math-editable', 'rows': 2}),
            'theory': forms.Textarea(attrs={'class': 'form-control math-editable', 'rows': 3}),
            'apparatus_scope': forms.Textarea(attrs={'class': 'form-control math-editable', 'rows': 2}),
            'procedure': forms.Textarea(attrs={'class': 'form-control math-editable', 'rows': 3}),
            'results': forms.Textarea(attrs={
                'class': 'form-control math-editable',
                'rows': 4,
                'placeholder': 'Record your experimental findings here …'
            }),
            'data_analysis': forms.Textarea(attrs={'class': 'form-control math-editable', 'rows': 3}),
            'discussion': forms.Textarea(attrs={'class': 'form-control math-editable', 'rows': 3}),
            'conclusion': forms.Textarea(attrs={'class': 'form-control math-editable', 'rows': 2}),
            'references': forms.Textarea(attrs={'class': 'form-control', 'rows': 2}),
            'report_file': forms.FileInput(attrs={'class': 'form-control'}),
            'data': forms.HiddenInput(),
            'graph_x_values': forms.HiddenInput(),
            'graph_y_values': forms.HiddenInput(),
        }
     
        labels = {
            'group_members': 'Group Members',
            'objective': 'Aim/Objectives of the Experiment',
            'theory': 'Introduction / Theory',
            'apparatus_scope': 'Apparatus Used',
            'procedure': 'Method / Procedure',
            'data_analysis': 'Data & Error Analysis',
            'discussion': 'Discussion',
            'conclusion': 'Conclusion',
            'references': 'References',
            'report_file': 'Upload Final Document (PDF/Docx)',
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        
      
        is_prelim_phase = not self.instance.is_preliminary_submitted

        if is_prelim_phase:

            final_stage_fields = ['data_analysis', 'discussion', 'conclusion', 'report_file']
            for field in final_stage_fields:
                self.fields[field].widget = forms.HiddenInput()
                self.fields[field].required = False
        else:
 
            prelim_stage_fields = ['group_members', 'objective', 'theory', 'apparatus_scope', 'procedure', 'results']
            for field in prelim_stage_fields:
                self.fields[field].widget.attrs['readonly'] = True

                self.fields[field].widget.attrs['class'] += ' locked-section bg-light'

    # --- sanitize logic ---
    def clean_objective(self): return _clean_latex(self.cleaned_data.get("objective"))
    def clean_theory(self): return _clean_latex(self.cleaned_data.get("theory"))
    def clean_apparatus_scope(self): return _clean_latex(self.cleaned_data.get("apparatus_scope"))
    def clean_procedure(self): return _clean_latex(self.cleaned_data.get("procedure"))
    def clean_results(self): return _clean_latex(self.cleaned_data.get("results"))
    def clean_data_analysis(self): return _clean_latex(self.cleaned_data.get("data_analysis"))
    def clean_discussion(self): return _clean_latex(self.cleaned_data.get("discussion"))
    def clean_conclusion(self): return _clean_latex(self.cleaned_data.get("conclusion"))
    def clean_references(self): return _clean_latex(self.cleaned_data.get("references"))
    
class ExperimentDraftForm(forms.ModelForm):
    class Meta:
        model = ExperimentDraft
        fields = ['observation', 'data', 'data_analysis', 'image']
        widgets = {
            'observation': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 4,
                'placeholder': 'Write your observations here...'
            }),
            'data': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 4,
                'placeholder': 'Record your data points or values here...'
            }),
            'data_analysis': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 4,
                'placeholder': 'Saved math (LaTeX) from math editor...'
            }),
            'image': forms.ClearableFileInput(attrs={
                'class': 'form-control'
            })
        }

    def clean_data_analysis(self):
        return _clean_latex(self.cleaned_data.get("data_analysis"))
    def clean_observation(self):
        return _clean_latex(self.cleaned_data.get("observation"))
    def clean_data(self):
        return _clean_latex(self.cleaned_data.get("data"))

def _clean_latex(text: str | None) -> str:
    """
    One-shot sanitiser for student LaTeX input.
    - strips HTML tags (Word, G-Docs paste)
    - normalises white-space & rogue literals
    - fixes common LaTeX typos
    - preserves line breaks for math environments
    """
    if not text:
        return ""
    text = re.sub(r'<[^>]+>', '', text)

    text = (text.replace('\x0a', '\n')
                .replace('&nbsp;', ' ')
                .replace('\\[', '$$')
                .replace('\\]', '$$'))

    text = re.sub(r"\^\{?\^", "^{", text)      # ^{^2} → ^{2}
    text = re.sub(r"\\\\+", r"\\", text)       # \\\\ → \\

    text = re.sub(r'\n\s*\n+', '\n', text)


    return text.strip()