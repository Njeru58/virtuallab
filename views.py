# Standard Library
import gzip
import hashlib
import json
import logging
import mimetypes
import os
import subprocess
from urllib.parse import quote

# Django Core & Settings
from django.conf import settings
from django.core.cache import cache
from django.core.mail import send_mail
from django.db import close_old_connections
from django.db.models import Prefetch, Q
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.urls import reverse
from django.core.mail import EmailMultiAlternatives

# Authentication, Users & Security
from django.contrib import messages
from django.contrib.auth import authenticate, get_user_model, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.tokens import default_token_generator
from django.contrib.sites.shortcuts import get_current_site
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST
from django.views.generic import ListView

# Utilities: Encoding, HTML & Time
from django.utils import timezone
from django.utils.html import strip_tags
from django.utils.encoding import force_bytes, force_str
from django.utils.html import escape, format_html
from django.utils.http import urlsafe_base64_decode, urlsafe_base64_encode
from django.contrib.auth.mixins import LoginRequiredMixin

# Local Virtuallab Models
from .models import (
    DBStoredImage,
    ExperimentAnswer,
    ExperimentDraft,
    ExperimentGraph,
    ExperimentQuestion,
    ExperimentReport,
    ExperimentStep,
    VirtualExperiment,
)

# Forms
from .forms import ExperimentReportForm, LabLoginForm, LabRegistrationForm

logger = logging.getLogger(__name__)
User = get_user_model()

User = get_user_model()
def lab_home_view(request):
    return render(request, 'virtuallab/home.html')

from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from .models import ExperimentDraft, ExperimentReport, VirtualExperiment


@login_required(login_url='lab:login')
def lab_dashboard_view(request):
  user = request.user

  # Experiments available to student's year group
  experiments_qs = VirtualExperiment.objects.all()
  if hasattr(user, 'year_group') and user.year_group:
    experiments_qs = experiments_qs.filter(year_group=user.year_group)

  total_experiments = experiments_qs.count()

  # Submissions & Evaluated Reports
  submitted_reports = ExperimentReport.objects.filter(
      student=user
  ).order_by('-submitted_at')
  total_submitted = submitted_reports.count()

  recent_evaluations = submitted_reports.filter(
      evaluation__isnull=False
  ).select_related('experiment', 'evaluation')[:4]

  # In-progress drafts
  drafts_qs = ExperimentDraft.objects.filter(student=user)
  total_drafts = drafts_qs.count()
  active_drafts = drafts_qs.select_related('experiment')[:3]

  context = {
      'total_experiments': total_experiments,
      'total_submitted': total_submitted,
      'total_drafts': total_drafts,
      'recent_evaluations': recent_evaluations,
      'active_drafts': active_drafts,
  }
  return render(request, 'virtuallab/dashboard.html', context)

def lab_login_view(request):
    if request.user.is_authenticated:
        return redirect('lab:experiment_list')

    if request.method == 'POST':
        form = LabLoginForm(request.POST)
        if form.is_valid():
            reg_or_username = form.cleaned_data.get('registration_number')
            password = form.cleaned_data.get('password')

            user = authenticate(request, username=reg_or_username, password=password)
            if not user:
                user_obj = User.objects.filter(registration_number__iexact=reg_or_username).first()
                if user_obj:
                    user = authenticate(request, username=user_obj.username, password=password)

            if user is not None:
                if user.is_active:
                    login(request, user)
                    next_url = request.GET.get('next') or request.POST.get('next')
                    return redirect(next_url or 'lab:dashboard')
                else:
                    messages.error(request, "This account is inactive. Please activate it via your email.")
            else:
                messages.error(request, "Invalid credentials. Please verify your Registration Number/Username and Password.")
    else:
        form = LabLoginForm()

    return render(request, 'virtuallab/auth/login.html', {
        'form': form,
        'title': 'Sign In',
        'next': request.GET.get('next', '')
    })


def lab_register_view(request):
  if request.user.is_authenticated:
    return redirect('lab:experiment_list')

  if request.method == 'POST':
    form = LabRegistrationForm(request.POST)
    if form.is_valid():
      user = form.save(commit=False)
      user.is_active = False
      user.save()
      form.save_m2m()

      # Generate activation payload
      current_site = get_current_site(request)
      token = default_token_generator.make_token(user)
      uid = urlsafe_base64_encode(force_bytes(user.pk))
      activation_url = reverse(
          'lab:activate', kwargs={'uidb64': uid, 'token': token}
      )
      scheme = 'https' if request.is_secure() else 'http'
      full_activation_url = f'{scheme}://{current_site.domain}{activation_url}'

      # Render multi-part email (plain text fallback + responsive HTML)
      html_content = render_to_string(
          'virtuallab/auth/activation_email.html',
          {
              'user': user,
              'activation_url': full_activation_url,
          },
      )
      text_content = strip_tags(html_content)

      email = EmailMultiAlternatives(
          subject='Activate your Virtual Physics Lab Account',
          body=text_content,
          from_email=None,  # Falls back to DEFAULT_FROM_EMAIL
          to=[user.email],
      )
      email.attach_alternative(html_content, 'text/html')
      email.send()

      return render(
          request,
          'virtuallab/auth/activation_notice.html',
          {
              'title': 'Activation Link Sent',
              'message': (
                  'An activation link has been sent to'
                  f' <strong>{user.email}</strong>. Please check your inbox to'
                  ' activate your account.'
              ),
              'back_url': reverse('lab:login'),
          },
      )
  else:
    form = LabRegistrationForm()

  return render(
      request,
      'virtuallab/auth/register.html',
      {'form': form, 'title': 'Create Account'},
  )


def lab_logout_view(request):
    logout(request)
    return redirect('lab:login')


def lab_activate_account(request, uidb64, token):
    try:
        uid = force_str(urlsafe_base64_decode(uidb64))
        user = User.objects.get(pk=uid)
    except (TypeError, ValueError, OverflowError, User.DoesNotExist):
        user = None

    if user is not None and default_token_generator.check_token(user, token):
        user.is_active = True
        user.save()
        messages.success(request, "Your laboratory account has been successfully activated. You can now log in.")
        return redirect('lab:login')
    else:
        return render(request, 'virtuallab/auth/activation_notice.html', {
            'title': 'Activation Failed',
            'message': 'The activation link is invalid or has expired.',
            'back_url': reverse('lab:login')
        })


def safe_json_load(data, default=None):
    """Safely load JSON data string or return default."""
    if default is None:
        default = []
    if not data:
        return default
    if isinstance(data, (dict, list)):
        return data
    try:
        return json.loads(data)
    except (json.JSONDecodeError, TypeError):
        return default



class ExperimentListView(LoginRequiredMixin, ListView):
  model = VirtualExperiment
  template_name = 'virtuallab/experiment_list.html'
  context_object_name = 'experiments'
  login_url = 'lab:login'

  def get_queryset(self):
    user = self.request.user
    now = timezone.now()

    # Base queryset filtered by user year group if present
    if hasattr(user, 'year_group') and user.year_group:
      experiments = list(
          VirtualExperiment.objects.filter(year_group=user.year_group)
      )
    else:
      experiments = list(VirtualExperiment.objects.all())

    # Annotate unlock status based on schedule
    for exp in experiments:
      if exp.unlock_time:
        exp.is_unlocked = exp.unlock_time <= now
      else:
        exp.is_unlocked = True

    return experiments

def experiment_detail(request, experiment_id):
    """
    Secure, high-performance experiment detail view.
    - Uses optimized SQL prefetching to prevent N+1 query overhead.
    - Avoids heavy ORM model pickling to keep memory footprints minimal.
    - Instantly syncs student drafts on page load.
    """
    user = request.user
    if not user.is_authenticated:
        return redirect('login')

    # Fetch experiment tree in a few optimized bulk SQL queries
    experiment = get_object_or_404(
        VirtualExperiment.objects.prefetch_related(
            'apparatus_items',
            'theory_images',
            Prefetch(
                'experimentstep_set',
                queryset=ExperimentStep.objects.order_by('step_number')
            ),
            'questions',
        ),
        pk=experiment_id,
    )

    # Pull active student draft fresh
    draft = (
        ExperimentDraft.objects
        .filter(experiment=experiment, student=user, is_active=True)
        .only('id', 'data', 'observation', 'image', 'last_updated')
        .order_by('-last_updated')
        .first()
    )

    draft_data = json.dumps(draft.data) if draft and draft.data else "[]"

    return render(
        request,
        "virtuallab/experiment_detail.html",
        {
            "experiment": experiment,
            "draft": draft,
            "draft_data": draft_data,
        },
    )

@csrf_exempt
@login_required
def auto_save_draft(request, experiment_id):
    """
    Auto-saves draft for an experiment.
    Accepts:
      - application/json payload
      - OR multipart/form-data with optional 'payload' JSON field
    Fields:
      - observation (string)
      - data (JSON string or object)
      - data_analysis (string, optional)
      - image (file, optional)
      - remove_image ("true" to delete)
    """
    if request.method != "POST":
        return JsonResponse({"status": "error", "error": "POST required"}, status=400)

    experiment = get_object_or_404(VirtualExperiment, id=experiment_id)

    # ------------------------------------------------------------------
    # Parse payload
    # ------------------------------------------------------------------
    payload = {}
    try:
        if request.content_type and "application/json" in request.content_type:
            payload = json.loads(request.body.decode("utf-8") or "{}")
        else:
            if request.POST.get("payload"):
                payload = json.loads(request.POST.get("payload"))
            else:
                payload = {
                    "observation": request.POST.get("observation", ""),
                    "data": request.POST.get("data", "[]"),
                    "data_analysis": request.POST.get("data_analysis", ""),
                }
    except Exception:
        logger.exception("auto_save_draft: failed to parse payload")
        return JsonResponse({"status": "error", "error": "Invalid payload"}, status=400)

    # Normalize table data
    raw_data = payload.get("data", "[]")
    try:
        data_json = json.loads(raw_data) if isinstance(raw_data, str) else raw_data
    except Exception:
        logger.exception("auto_save_draft: invalid JSON for data")
        data_json = []



    observation   = payload.get("observation", "")
    data_analysis = normalize_latex(payload.get("data_analysis", ""))

    image_file   = request.FILES.get("image")
    remove_image = str(payload.get("remove_image", "")).lower() == "true" or request.POST.get("remove_image", "").lower() == "true"



    # ------------------------------------------------------------------
    # Save or update draft
    # ------------------------------------------------------------------
    draft, created = ExperimentDraft.objects.update_or_create(
        experiment=experiment,
        student=request.user,
        version=1,  # or the version you want for autosave
        defaults={
            "observation": observation,
            "data": data_json,
            "data_analysis": data_analysis,
            "created_at": timezone.now(),
            "last_updated": timezone.now(),
        }
    )


    # Update fields
    draft.observation   = observation or draft.observation
    draft.data          = data_json
    draft.data_analysis = data_analysis or draft.data_analysis


    # ------------------------------------------------------------------
    # Graph handling (clean, safe)
    # ------------------------------------------------------------------
    graph_points_raw = request.POST.get('graph_points_json') or payload.get('graph_points_json')
    graph_vector_raw = request.POST.get('graph_vector_json') or payload.get('graph_vector_json')
    graph_image_data_raw = request.POST.get('graph_image_data') or payload.get('graph_image_data')

    # ----- Points JSON -----
    if graph_points_raw:
        if isinstance(graph_points_raw, str):
            draft.graph_points_json = safe_json_load(graph_points_raw, default=[])
        else:
            draft.graph_points_json = graph_points_raw

    # ----- Vector JSON -----
    if graph_vector_raw:
        if isinstance(graph_vector_raw, str):
            draft.graph_vector_json = safe_json_load(graph_vector_raw, default={})
        else:
            draft.graph_vector_json = graph_vector_raw

    # ----- Base64 Images -----
    # Supports multiple images stored in a related model (GraphImage)
    if graph_image_data_raw:
        try:
            images_list = safe_json_load(graph_image_data_raw, default=[])
            for i, img_b64 in enumerate(images_list):
                if img_b64.startswith('data:'):
                    header, b64 = img_b64.split(',', 1)
                    ext = 'svg' if 'svg' in header else 'png'
                    filename = f'graph_{draft.id}_{i}.{ext}'

                    # If you have a single ImageField:
                    # draft.graph_images.save(filename, ContentFile(base64.b64decode(b64)), save=False)

                    # If you have a related GraphImage model:
                    # GraphImage.objects.create(
                    #     draft=draft,
                    #     image=ContentFile(base64.b64decode(b64), name=filename)
                    # )
        except Exception as e:
            logger.exception(f"Failed to save graph images: {e}")




    # ------------------------------------------------------------------
    # Image handling
    # ------------------------------------------------------------------
    if image_file:                     # new upload
        draft.image = image_file
    elif remove_image:                 # explicit delete
        draft.image = None
    # else → keep existing image

    draft.last_updated = timezone.now()
    draft.save()



    # ------------------------------------------------------------------
    # Response
    # ------------------------------------------------------------------
    resp = {
        "status": "saved",
        "draft_id": draft.id,
        "created": created,
        "last_updated": draft.last_updated.isoformat(),
        "observation": draft.observation,
        "data": draft.data,
        "data_analysis": draft.data_analysis,
    }
    if draft.image:
        resp["image_url"] = draft.image.url  # 🔥 frontend reload preview
    from django.core.cache import cache
    cache_key = f"experiment_detail_{experiment_id}_user_{request.user.id}"
    cache.delete(cache_key)

    return JsonResponse(resp, status=200)
@login_required
def submit_report(request, experiment_id):
    experiment = get_object_or_404(VirtualExperiment, pk=experiment_id)
    questions = experiment.questions.all()

    report, created = ExperimentReport.objects.get_or_create(
        student=request.user,
        experiment=experiment,
        defaults={'submitted_at': None}
    )

    draft = ExperimentDraft.objects.filter(
        experiment=experiment,
        student=request.user,
        is_active=True
    ).first()

    # --- Draft Data Preparation (Kept as is) ---
    draft_data = []
    if draft and draft.data:
        if isinstance(draft.data, list): draft_data = draft.data
        elif isinstance(draft.data, str): draft_data = safe_json_load(draft.data, [])
    
    for table in draft_data:
        if isinstance(table, dict):
            table.setdefault('columns', ['Column 1'])
            table['columns'] = [c or f'Column {i+1}' for i, c in enumerate(table['columns'])]

    if request.method == 'POST':
        form = ExperimentReportForm(request.POST, request.FILES, instance=report)
        if form.is_valid():
            report_instance = form.save(commit=False)

            # STAGE 1: Submitting Preliminary Data
            if not report.is_preliminary_submitted:
                report_instance.is_preliminary_submitted = True
                report_instance.preliminary_submitted_at = timezone.now()
                
                # Copy raw data from draft to report if present
                if draft:
                    report_instance.data = draft.data
                
                report_instance.save()
                messages.success(request, "Preliminary data saved! Final analysis sections are now unlocked.")
                return redirect('lab:submit_report', experiment_id=experiment.id)

            # STAGE 2: Submitting Final Report
            else:
                report_instance.submitted_at = timezone.now()
                report_instance.save()

                # Handle Graphs and Answers only during Final phase
                points_list = safe_json_load(request.POST.get('graph_points_json') or '[]')
                ExperimentGraph.objects.filter(report=report_instance).delete()
                for i, graph_data in enumerate(points_list):
                    labels = graph_data.get('labels', {})
                    ExperimentGraph.objects.create(
                        report=report_instance,
                        points_json=graph_data.get('points', []),
                        title=labels.get('title', 'Untitled'),
                        x_label=labels.get('xlabel', 'X'),
                        y_label=labels.get('ylabel', 'Y')
                    )

                for q in questions:
                    ans = request.POST.get(f"question_{q.id}", "").strip()
                    if ans:
                        ExperimentAnswer.objects.update_or_create(
                            report=report_instance, question=q,
                            defaults={'answer_text': ans}
                        )

                if draft:
                    draft.is_active = False
                    draft.save()

                messages.success(request, "Final report submitted successfully.")
                return redirect('lab:report_submitted', experiment.id)
    else:
            # GET logic: Prefill from draft if strictly in prelim phase
            initial = {}
            if not report.is_preliminary_submitted and draft:
                # Use draft observation ONLY if the report field is currently empty
                if not report.observation:
                    initial['observation'] = draft.observation
                if not report.results:
                    initial['results'] = draft.observation 
                
                # Sync table data if report is empty
                if not report.data or report.data == "[]":
                    report.data = draft.data
                    # Force update the variable used for the template tables
                    draft_data = draft.data 

            form = ExperimentReportForm(instance=report, initial=initial)

    answers = {a.question.id: a.answer_text for a in ExperimentAnswer.objects.filter(report=report)}

    context = {
        'experiment': experiment,
        'form': form,
        'questions': questions,
        'report': report,
        'report_answers': answers if request.method != 'POST' else request.POST,
        'submitted': report.submitted_at is not None,
        'is_preliminary': not report.is_preliminary_submitted, # Helper for template
        'draft_data': json.dumps(draft_data),
    }

    return render(request, 'virtuallab/submit_report.html', context)


@login_required
def report_submitted(request, experiment_id):
    experiment = get_object_or_404(VirtualExperiment, id=experiment_id)

    report = (
        ExperimentReport.objects
        .filter(experiment=experiment, student=request.user)
        .order_by('-submitted_at')
        .first()
    )
    
    if not report:
        messages.error(request, "No report found for this experiment.")
        return redirect('lab:experiment_list')

    # --- Helper: LaTeX to Cleaned Lines Converter ---
    def clean_latex_to_lines(raw_text):
        if not raw_text:
            return []
        # split on '\\' or newlines
        raw_lines = re.split(r'\\\\|\n', str(raw_text))
        cleaned_lines = []
        for raw in raw_lines:
            line = raw.strip()
            if not line: continue

            # 1. Remove existing display math wrappers
            line = re.sub(r'(?s)\$\$(.*?)\$\$', r'\1', line)
            line = re.sub(r'(?s)\\\[(.*?)\\\]', r'\1', line)

            # 2. Clean and protect text macros
            line = re.sub(
                r'\\text\s*\{(.*?)\}',
                lambda m: f"\\text{{{m.group(1).replace('=', '＝')}}}",
                line
            )

            # 3. Balance braces safely
            diff = line.count('{') - line.count('}')
            if diff > 0:
                line += '}' * diff
            elif diff < 0:
                line = line[:diff]
            
            cleaned_lines.append(line)
        return cleaned_lines

    # --- State Logic ---
    # If submitted_at is null, they just finished the Preliminary phase.
    is_preliminary_only = report.submitted_at is None and report.is_preliminary_submitted

    # --- Decode experimental data safely ---
    experimental_tables = []
    if report.data:
        loaded = report.data
        if isinstance(loaded, list) and loaded:
            if isinstance(loaded[0], dict):
                for tbl in loaded:
                    cols = tbl.get("columns", [])
                    rows = tbl.get("data", [])
                    experimental_tables.append([cols] + rows)
            else:
                experimental_tables = loaded

    # --- Questions & Answers (Only relevant for Final stage) ---
    questions = ExperimentQuestion.objects.filter(experiment=experiment)
    answers = {}
    if not is_preliminary_only:
        answers_qs = ExperimentAnswer.objects.filter(report=report)
        answers = {a.question.id: a.answer_text for a in answers_qs}

    # --- Section Assembly with LaTeX Support ---
    # We now clean ALL major sections in case they contain equations
    full_sections_list = [
        ('Group Members', str(report.group_members or "")), # Usually plain text
        ('Objective', clean_latex_to_lines(report.objective)),
        ('Theory', clean_latex_to_lines(report.theory)),
        ('Apparatus Used', clean_latex_to_lines(report.apparatus_scope)),
        ('Procedure', clean_latex_to_lines(report.procedure)),
        ('Results', clean_latex_to_lines(report.results)),
        ('Data & Error Analysis', clean_latex_to_lines(report.data_analysis)),
        ('Discussion', clean_latex_to_lines(report.discussion)),
        ('Conclusion', clean_latex_to_lines(report.conclusion)),
        ('References', str(report.references or "")),
    ]

    # Filter sections based on current progress
    prelim_headers = ['Group Members', 'Objective', 'Theory', 'Apparatus Used', 'Procedure', 'Results']
    
    if is_preliminary_only:
        # Only show prelim sections
        display_sections = [s for s in full_sections_list if s[0] in prelim_headers]
    else:
        # Show everything
        display_sections = full_sections_list

    context = {
        'experiment': experiment,
        'report': report,
        'experimental_tables': experimental_tables,
        'questions': questions if not is_preliminary_only else [],
        'answers': answers,
        'sections': display_sections,
        'is_preliminary_only': is_preliminary_only,
    }

    return render(request, 'virtuallab/report_submitted.html', context)
@login_required
def report_pdf(request, experiment_id):
    """Generate a branded PDF version of the submitted lab report (safe for LaTeX equations)."""
    report = get_object_or_404(
        ExperimentReport,
        experiment_id=experiment_id,
        student=request.user,
        submitted_at__isnull=False
    )

    experiment = report.experiment
    questions = experiment.questions.all()
    answers = {
        a.question.id: a.answer_text
        for a in ExperimentAnswer.objects.filter(report=report)
    }

    # ---- Rebuild Experimental Tables ----
    experimental_tables = []
    if report.data:
        loaded = report.data
        if isinstance(loaded, list) and loaded:
            if isinstance(loaded[0], dict):
                for tbl in loaded:
                    cols = tbl.get("columns", [])
                    rows = tbl.get("data", [])
                    experimental_tables.append([cols] + rows)
            else:
                experimental_tables = loaded

    # ---- Data & Error Analysis: Safe LaTeX Rendering ----
    data_analysis_lines = []
    if report.data_analysis:
        try:
            clean = report.data_analysis
        except Exception as e:
            logger.warning(f"normalize_latex failed during PDF export: {e}")
            clean = report.data_analysis

        for raw in clean.split(r'\\'):
            line = raw.strip()
            if not line:
                continue

            # Strip wrapper tokens
            line = re.sub(r'(?s)\$\$(.*?)\$\$', r'\1', line)
            line = re.sub(r'(?s)\\\[\s*(.*?)\s*\\\]', r'\1', line)

            try:
                svg = latex_to_svg(line)
                data_analysis_lines.append(svg)
            except Exception as e:
                logger.warning(f"latex_to_svg failed for line: {line[:50]} – {e}")
                # fallback: render plain text safely
                data_analysis_lines.append(f"<p>{escape(line)}</p>")

    # ---- Section Layout ----
    sections = [
        ('Group Members', str(report.group_members or "")),
        ('Objective', str(report.objective or "")),
        ('Theory', str(report.theory or "")),
        ('Apparatus Used', str(report.apparatus_scope or "")),
        ('Procedure', str(report.procedure or "")),
        ('Results', str(report.results or "")),
        ('Data & Error Analysis', data_analysis_lines),
        ('Discussion', str(report.discussion or "")),
        ('Conclusion', str(report.conclusion or "")),
        ('References', str(report.references or "")),
    ]

    context = {
        'report': report,
        'experiment': experiment,
        'sections': sections,
        'experimental_tables': experimental_tables,
        'questions': questions,
        'answers': answers,
        'STATIC_ROOT': settings.STATIC_ROOT,
    }

    # ---- Render HTML for WeasyPrint ----
    html_string = render_to_string('virtuallab/report_pdf.html', context)

    # ---- Generate the PDF ----
    response = HttpResponse(content_type='application/pdf')
    response['Content-Disposition'] = (
        f'attachment; filename="{experiment.code}_{request.user.username}.pdf"'
    )

    base_url = request.build_absolute_uri('/')
    import weasyprint
    weasyprint.HTML(string=html_string, base_url=base_url).write_pdf(
        response,
        presentational_hints=True
    )

    return response


@login_required
def my_evaluated_reports(request):
    reports = ExperimentReport.objects.filter(student=request.user).prefetch_related('evaluation')
    return render(request, 'virtuallab/report_list.html', {'reports': reports})
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, get_object_or_404
from django.core.exceptions import PermissionDenied, ObjectDoesNotExist
@login_required
def view_report_detail(request, report_id):
    report = get_object_or_404(ExperimentReport, id=report_id)

    if report.student != request.user:
        raise PermissionDenied("You do not have permission to view this report.")

    # ----------------  ALWAYS initialise context  ----------------
    context = {
        'report': report,
        'sections': [
            ('objective', 'Objective', 'bullseye'),
            ('theory', 'Theory', 'book'),
            ('apparatus_scope', 'Apparatus Used', 'tools'),
            ('procedure', 'Procedure', 'list-ol'),
            ('results', 'Results', 'chart-line'),
            ('data_analysis', 'Data & Error Analysis', 'search'),
            ('discussion', 'Discussion', 'comments'),
            ('conclusion', 'Conclusion', 'check-circle'),
            ('references', 'References', 'link'),
        ],
        'experimental_tables': [],
        'observation_text': '',
        'data_analysis_lines': [],
        'overall_score': None,
        'not_evaluated': False,
        'scores': {},
        'feedback': {},
    }

    # ----------------  Experimental tables  ----------------
    if report.data:
        loaded = report.data
        if isinstance(loaded, list) and loaded:
            if isinstance(loaded[0], dict):
                for tbl in loaded:
                    cols = tbl.get("columns", [])
                    rows = tbl.get("data", [])
                    context['experimental_tables'].append([cols] + rows)
            else:
                context['experimental_tables'] = loaded

    # ----------------  Observation  ----------------
    latest_draft = (
        ExperimentDraft.objects
        .filter(experiment=report.experiment, student=request.user, is_active=False)
        .order_by('-last_updated')
        .first()
    )
    context['observation_text'] = (
        latest_draft.observation if latest_draft else (report.results or "")
    )

    # ----------------  Data-analysis → MathJax/Katex (RAW)  ----------------
    data_analysis_lines = []
    if report.data_analysis:
        clean = report.data_analysis
        raw_lines = re.split(r'\\\\|\n', clean)  # split on '\\' or newlines

        for raw in raw_lines:
            line = raw.strip()
            if not line:
                continue

            # Remove math wrappers
            line = re.sub(r'(?s)\$\$(.*?)\$\$', r'\1', line)
            line = re.sub(r'(?s)\\\[(.*?)\\\]', r'\1', line)

            # Protect text macros
            line = re.sub(
                r'\\text\s*\{(.*?)\}',
                lambda m: f"\\text{{{m.group(1).replace('=', '＝')}}}",
                line
            )

            # Balance braces safely
            diff = line.count('{') - line.count('}')
            if diff > 0:
                line += '}' * diff
            elif diff < 0:
                line = line[:diff]

            data_analysis_lines.append(line)

    context['data_analysis_lines'] = data_analysis_lines

    # ----------------  Evaluation  ----------------
    try:
        scores = {}
        feedback = {}
        for section, score in report.evaluation.scores.items():
            scores[section] = score.get("rubric", 0) if isinstance(score, dict) else score
            feedback[section] = report.evaluation.feedback.get(section, "")
        if scores:
            context['overall_score'] = round(sum(scores.values()) / len(scores), 1)
            context['scores'] = scores
            context['feedback'] = feedback
    except ObjectDoesNotExist:
        context['not_evaluated'] = True

    return render(request, 'virtuallab/report_detail.html', context)

def view_responses(self, obj):
    responses = obj.responses.all()
    if not responses:
        return "No responses"
    
    html = "<ul style='padding-left:1rem;'>"
    for r in responses:
        status = "✅" if r.is_correct else "❌"
        answer_display = r.answer or f"Option {r.selected_option}" if r.selected_option else "—"
        html += f"<li><b>{r.question.question_text[:40]}...</b><br>Answer: {answer_display}<br>{status} Marks: {getattr(r, 'marks_awarded', '-')}</li><hr>"
    html += "</ul>"
    return format_html(html)


@csrf_exempt
@login_required
def auto_save_report(request, experiment_id):
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            experiment = get_object_or_404(VirtualExperiment, pk=experiment_id)
            report, _ = ExperimentReport.objects.get_or_create(student=request.user, experiment=experiment)

            # Update only if the key exists in model fields
            for field in [
                'group_members', 'objective', 'theory', 'apparatus_scope',
                'procedure', 'results', 'data_analysis', 'discussion',
                'conclusion', 'references', 'observation', 'data'
            ]:
                if field in data:
                    setattr(report, field, data[field])
            report.save()
            return JsonResponse({'status': 'success'})
        except Exception as e:
            return JsonResponse({'status': 'error', 'message': str(e)}, status=400)

    return JsonResponse({'status': 'invalid method'}, status=405)


def dbmedia_view(request, filepath):
    """
    Serves binary images stored in the database via DatabaseStorage.
    Supports gzip compression, browser caching, and inline display.
    """
    # ✅ Keep POSIX-style path (don't replace slashes)
    try:
        obj = DBStoredImage.objects.get(name=filepath)
    except DBStoredImage.DoesNotExist:
        raise Http404("Image not found")

    content_type = (
        obj.content_type
        or mimetypes.guess_type(obj.name)[0]
        or "application/octet-stream"
    )

    data = bytes(obj.data)  # Ensure it's bytes (BinaryField-safe)
    safe_name = quote(obj.name.encode("utf-8"), safe="")

    # ✅ Optional gzip if large enough & accepted
    if "gzip" in request.META.get("HTTP_ACCEPT_ENCODING", "") and len(data) > 2048:
        data = gzip.compress(data, compresslevel=6)
        response = HttpResponse(data, content_type=content_type)
        response["Content-Encoding"] = "gzip"
    else:
        response = HttpResponse(data, content_type=content_type)

    response["Content-Length"] = str(len(data))
    response["Cache-Control"] = "public, max-age=86400"   # Cache 1 day
    response["Content-Disposition"] = f'inline; filename="{safe_name}"'

    return response

from re import sub   # already imported

def tex_escape_text(s: str) -> str:
    """
    Escape characters that are special inside \text{...}
    We only care about the ones students actually type.
    """
    return (
        s.replace('\\', r'\textbackslash{}')
         .replace('{', r'\{')
         .replace('}', r'\}')
         .replace('$', r'\$')
         .replace('&', r'\&')
         .replace('%', r'\%')
         .replace('#', r'\#')
         .replace('^', r'\textasciicircum{}')
         .replace('_', r'\_')
         .replace('=', r'\ensuremath{=}')   # <-- the critical one
         .replace('~', r'\textasciitilde{}')
    )

def protect_text_macros(s: str) -> str:
    """Escape math-sensitive chars inside every \text{...} block."""
    return sub(r'\\text\{([^}]*)\}',
               lambda m: r'\text{' + tex_escape_text(m.group(1)) + '}', s)


logger = logging.getLogger(__name__)

def latex_to_svg(math_expr: str) -> str:
    """
    Render LaTeX → SVG safely with KaTeX via Node.
    Handles DB safety, timeouts, caching, and invalid math gracefully.
    """
    if not math_expr or not math_expr.strip():
        return ""

    # Sanitize input (but don’t over-escape!)
    expr = str(math_expr).strip()
    expr = re.sub(r"[\u200b-\u200d\uFEFF]", "", expr)  # remove zero-width chars
    expr = expr.replace("d\\text", "\\text")            # fix common typo

    key = f"katex_svg_{hashlib.sha1(expr.encode()).hexdigest()}"
    cached = cache.get(key)
    if cached:
        return cached

    close_old_connections()

    try:
        proc = subprocess.run(
            ['node'] + settings.KATEX_CMD + ['--display-mode', '--trust'],
            input=expr,
            text=True,
            capture_output=True,
            timeout=6,
        )

        if proc.returncode == 0 and proc.stdout.strip():
            svg = proc.stdout.strip()
            cache.set(key, svg, 60 * 60 * 12)
            return svg
        else:
            logger.error("KaTeX render failed: %s | %s", expr, proc.stderr)
            return f"<span style='color:red;'>{expr}</span>"

    except subprocess.TimeoutExpired:
        logger.warning("KaTeX timeout for: %s", expr[:50])
        return "<span style='color:orange;'>[KaTeX Timeout]</span>"

    except Exception as e:
        logger.exception("KaTeX crash: %s", e)
        return f"<span style='color:red;'>[Render Error]</span>"

    finally:
        close_old_connections()



def unicode_to_latex(text: str) -> str:
    r"""Replace Unicode math symbols in text with LaTeX equivalents."""
    for uni, tex in UNICODE_TO_LATEX.items():
        text = text.replace(uni, tex)
    return text

## --- Improved LaTeX Normalizer (Safe Version) ---
import re
from django.utils.safestring import mark_safe

# ------------------------------------------------------------------
# 1.  Unicode → LaTeX map  (your original list, kept)
# ------------------------------------------------------------------
UNICODE_TO_LATEX = {
    "π": r"\pi",
    "²": "^{2}",
    "³": "^{3}",
    "×": r"\times",
    "÷": r"\div",
    "−": "-",                # true minus
    "≤": r"\leq",
    "≥": r"\geq",
    "≠": r"\neq",
    "√": r"\sqrt{}",
    "∞": r"\infty",
    "α": r"\alpha",
    "β": r"\beta",
    "θ": r"\theta",
    "μ": r"\mu",
    "σ": r"\sigma",
    "Σ": r"\Sigma",
    "Δ": r"\Delta",
    "∆": r"\Delta",          # alt delta
    "λ": r"\lambda",
    "ρ": r"\rho",
    "θ": r"\theta",
    "μ": r"\mu",
    "σ": r"\sigma",
    "∞": r"\infty",
    "∑": r"\sum",
    "∫": r"\int",
    "√": r"\sqrt",
    "½": r"\frac{1}{2}",
    "⅓": r"\frac{1}{3}",
    "⅔": r"\frac{2}{3}",
    "¼": r"\frac{1}{4}",
    "¾": r"\frac{3}{4}",
    "⅕": r"\frac{1}{5}",
    "⅖": r"\frac{2}{5}",
    "⅗": r"\frac{3}{5}",
    "⅘": r"\frac{4}{5}",
    "⅙": r"\frac{1}{6}",
    "⅚": r"\frac{5}{6}",
    "⅛": r"\frac{1}{8}",
    "⅜": r"\frac{3}{8}",
    "⅝": r"\frac{5}{8}",
    "⅞": r"\frac{7}{8}",
}

# ------------------------------------------------------------------
# 2.  Main normaliser  (storage + Unicode + safety + rendering)
# ------------------------------------------------------------------
import re, html, logging
logger = logging.getLogger(__name__)

def normalize_latex(text: str) -> str:
    """
    Cleans and normalizes LaTeX for safe DB storage.
    Handles unbalanced braces, rogue $$, and malformed \\displaylines.
    """
    if not text or not isinstance(text, str):
        return ""

    # --- 0. HTML + rogue bytes ---
    text = html.unescape(text)
    text = re.sub(r'<[^>]+>', '', text)
    text = (text.replace('\x0a', '\n')
                .replace('&nbsp;', ' ')
                .replace('\\[', '$$')
                .replace('\\]', '$$'))

    # --- 1. Unicode replacement ---
    for uni, latex in UNICODE_TO_LATEX.items():
        text = text.replace(uni, latex)

    # --- 2. Dangerous command removal ---
    banned = [
        r'\\input', r'\\write', r'\\openout', r'\\read', r'\\file',
        r'\\loop', r'\\catcode', r'\\immediate', r'\\every',
        r'\\includegraphics', r'\\usepackage', r'\\def'
    ]
    text = re.sub('|'.join(banned), '', text, flags=re.IGNORECASE)

    # --- 3. Syntax & displayline fixes ---
    text = re.sub(r'\\frac(\d)(\d)', r'\\frac{\1}{\2}', text)

    # Remove stray opening brace right after $$ 
    text = re.sub(r'\$\$\s*\{', '$$ ', text)

    # Normalize \displaylines to ensure proper braces
    text = re.sub(r'\\displaylines(?!\s*\{)', r'\\displaylines{', text)

    # Ensure each \displaylines{...} has a closing }
    text = re.sub(r'(\\displaylines\{[^}]*)($|\$\$)', r'\1}', text)


    # --- 4. Balance braces globally ---
    def balance_braces(s: str) -> str:
        open_b = s.count('{')
        close_b = s.count('}')
        if open_b > close_b:
            s += '}' * (open_b - close_b)
        elif close_b > open_b:
            s = ('{' * (close_b - open_b)) + s
        return s

    # Fix unbalanced $$ pairs
    dollar_count = text.count('$$')
    if dollar_count % 2 != 0:
        logger.warning("Odd $$ count detected; appending closing $$")
        text += '$$'

    # --- 5. Clean each line ---
    cleaned_lines = []
    for line in text.splitlines():
        line = balance_braces(line.strip())
        if not line:
            continue
        if re.match(r'^(\\sum|\\int|\\lim|\\displaystyle|\\frac|\\text|\\displaylines)', line) and not re.search(r'\$\$.*\$\$', line):
            line = f'$$ {line} $$'
        cleaned_lines.append(line)

    # Collapse spaces, final cleanup
    cleaned = re.sub(r'\s+', ' ', '\n'.join(cleaned_lines)).strip()
    return cleaned