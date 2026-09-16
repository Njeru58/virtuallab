import logging
from celery import shared_task
from django.contrib.auth import get_user_model
from virtuallab.models import ExperimentReport
from virtuallab.services.report_evaluation import evaluate_reports_service

logger = logging.getLogger(__name__)

@shared_task(bind=True)
def evaluate_reports_task(self, report_ids, evaluator_id):
    reports = ExperimentReport.objects.filter(id__in=report_ids)
    User = get_user_model()
    evaluator = User.objects.get(pk=evaluator_id)

    logger.info(f"STARTING background evaluation of {len(report_ids)} reports by evaluator {evaluator.username}...")
    evaluated, _ = evaluate_reports_service(reports=reports, evaluator=evaluator)
    logger.info(f"FINISHED background evaluation: {evaluated} reports evaluated.")
    return {"evaluated": evaluated}