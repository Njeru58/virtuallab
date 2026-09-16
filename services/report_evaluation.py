import logging
import os
from django.conf import settings
from django.db import transaction
from django.urls import reverse

# Local virtuallab models
from virtuallab.models import ReportEvaluation

# Ensure constants and helper evaluators live inside virtuallab/constants.py
from virtuallab.constants import (
    LAB_RUBRIC,
    evaluate_apparatus_scope,
    evaluate_theory,
    evaluate_objective,
    evaluate_procedure,
    evaluate_lab_report_unified,
)

logger = logging.getLogger(__name__)


def _send_report_notification(evaluator, student, exp_title, report_id):
    """
    Safely dispatches a notification if a Notification model exists,
    allowing virtuallab to function even if decoupled from QuestionBank.
    """
    try:
        from QuestionBank.models import Notification
        link_url = reverse('lab:report_detail', args=[report_id])

        if not Notification.objects.filter(
            users=student, 
            link=link_url, 
            type='success'
        ).exists():
            notif = Notification.objects.create(
                sender=evaluator,
                message=f"Your report for '{exp_title}' has been evaluated.",
                link=link_url,
                type='success',
            )
            notif.users.add(student)
    except (ImportError, Exception) as exc:
        logger.warning(f"Notification bypassed or failed: {exc}")


def evaluate_reports_service(*, reports, evaluator):
    """
    Orchestrates the evaluation of lab reports using a hybrid approach:
    1. Deterministic (CPU) checks for objective, theory, apparatus, procedure.
    2. Unified AI (Gemini) check for measurements, analysis, discussion, references.
    """
    logger.info(f"Starting unified evaluation of {reports.count()} report(s) by {evaluator.username}")

    # Safety check for API Key
    if not (getattr(settings, "GEMINI_API_KEY", None) or os.getenv("GEMINI_API_KEY")):
        logger.error("GEMINI_API_KEY not configured. Aborting evaluation.")
        return 0, reports.count()

    evaluated = 0

    for report in reports.iterator():
        logger.info(f"Evaluating report ID {report.id}...")
        exp = report.experiment

        try:
            # =========================================================
            # PHASE 1: DETERMINISTIC CHECKS (CPU ONLY - FAST)
            # =========================================================
            apparatus_res = evaluate_apparatus_scope(report, exp)
            theory_res    = evaluate_theory(report, exp)
            objective_res = evaluate_objective(report, exp)
            procedure_res = evaluate_procedure(report, exp)

            # =========================================================
            # PHASE 2: UNIFIED AI EVALUATION (SINGLE API CALL)
            # =========================================================
            unified_res = evaluate_lab_report_unified(report, exp)

            # =========================================================
            # PHASE 3: MAP TO DATABASE SCHEMA
            # =========================================================
            scores = {}
            feedback = {}

            # --- A. Map Deterministic Results ---
            scores["apparatus_scope"] = {
                "rubric": apparatus_res["rubric"],
                "coverage_percent": apparatus_res.get("coverage_percent"),
                "matched": apparatus_res.get("matched"),
                "missing": apparatus_res.get("missing"),
            }
            feedback["apparatus_scope"] = apparatus_res["feedback"]

            scores["theory"] = {"rubric": theory_res["rubric"]}
            feedback["theory"] = theory_res["feedback"]

            scores["objective"] = {"rubric": objective_res["rubric"]}
            feedback["objective"] = objective_res["feedback"]

            scores["procedure"] = {
                "rubric": procedure_res["rubric"],
                "coverage_percent": procedure_res.get("coverage_percent"),
                "missing_steps": procedure_res.get("missing_steps"),
                "tense_issues": procedure_res.get("tense_issues"),
            }
            feedback["procedure"] = procedure_res["feedback"]

            # --- B. Map Unified AI Results ---
            scores["results"] = unified_res["measurements"]
            feedback["results"] = unified_res["measurements"]["feedback"]

            scores["data_analysis"] = unified_res["analysis"]
            feedback["data_analysis"] = unified_res["analysis"]["feedback"]

            scores["discussion"] = {
                "rubric": unified_res["discussion"]["rubric"]["discussion"],
                "checklist": unified_res["discussion"]["checklist"]
            }
            feedback["discussion"] = unified_res["discussion"]["feedback"]["discussion"]

            scores["conclusion"] = {
                "rubric": unified_res["discussion"]["rubric"]["conclusion"],
                "general_notes": unified_res["discussion"]["feedback"]["general_notes"]
            }
            feedback["conclusion"] = unified_res["discussion"]["feedback"]["conclusion"]

            scores["references"] = unified_res["references"]
            feedback["references"] = unified_res["references"]["feedback"]

            # =========================================================
            # PHASE 4: SAVE & NOTIFY
            # =========================================================
            with transaction.atomic():
                ReportEvaluation.objects.update_or_create(
                    report=report,
                    defaults={
                        "scores": scores,
                        "feedback": feedback,
                        "evaluator": evaluator
                    },
                )
                
                _send_report_notification(
                    evaluator=evaluator,
                    student=report.student,
                    exp_title=exp.title,
                    report_id=report.id
                )

            evaluated += 1
            logger.info(f"Report {report.id} evaluation saved successfully.")

        except Exception as e:
            logger.error(f"Failed to evaluate report {report.id}: {e}", exc_info=True)
            continue

    logger.info(f"Finished evaluating {evaluated} reports.")
    return evaluated, 0