from django.db import models
from django.conf import settings
from django.utils import timezone
from django.contrib.auth import get_user_model
from django.utils.functional import cached_property
from django_ckeditor_5.fields import CKEditor5Field

from cloudinary_storage.storage import MediaCloudinaryStorage as CloudinaryImageStorage
from .storage_backends import VideoCloudinaryStorage 
from .storage import DatabaseStorage

YEAR_CHOICES = [
    ('1', '1st Year'),
    ('2', '2nd Year'),
    ('3', '3rd Year'),
    ('4', '4th Year'),
]

class Programme(models.Model):
    name = models.CharField(max_length=255)
    code = models.CharField(max_length=20, unique=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "QuestionBank_programme"
        managed = False

    def __str__(self):
        return f"{self.name} ({self.code})"


class VirtualExperiment(models.Model):
    title = models.CharField(max_length=200)
    code = models.CharField(max_length=50)
    
    objective = CKEditor5Field('Objective', config_name='default', blank=True, null=True)
    theory = CKEditor5Field('Theory', config_name='default', blank=True, null=True)
    method_summary = CKEditor5Field('Method Summary', config_name='default', blank=True, null=True)

    recording_guide_tables = CKEditor5Field(
        'Data Recording Guide', 
        config_name='default', 
        blank=True, 
        null=True,
        help_text="Create or paste reference tables and guidelines for students here."
    )
    video_url = models.URLField(blank=True, null=True)

    year_group = models.CharField(  
        max_length=10,
        choices=YEAR_CHOICES,
        help_text="Select the year group this experiment is for"
    )
    unlock_time = models.DateTimeField(default=timezone.now, help_text="When this experiment becomes available")
    lock_time = models.DateTimeField(null=True, blank=True, help_text="Deadline after which reports can no longer be submitted")

    requires_report = models.BooleanField(default=True)
    requires_questions = models.BooleanField(default=False)
    needs_graph = models.BooleanField(default=False, help_text="Check if this experiment requires a graph editor")

    class Meta:
        db_table = "QuestionBank_virtualexperiment"
        verbose_name = "Virtual Experiment"
        verbose_name_plural = "Virtual Experiments"

    def __str__(self):
        return self.title


class ApparatusItem(models.Model):
    experiment = models.ForeignKey(
        "VirtualExperiment",
        on_delete=models.CASCADE,
        related_name="apparatus_items",
    )
    name = models.CharField(max_length=100)
    image = models.ImageField(
        storage=CloudinaryImageStorage(),
        upload_to="apparatus_items/",
    )

    class Meta:
        db_table = "QuestionBank_apparatusitem"
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name

    def save(self, *args, **kwargs):
        if self.image:
            self.image.name = self.image.name.replace("\\", "/")
        super().save(*args, **kwargs)

    @cached_property
    def thumb_url(self) -> str:
        if not self.image:
            return ""
        return f"{self.image.url}?f=auto&q=auto&w=400"


class TheoryImage(models.Model):
    experiment = models.ForeignKey(
        "VirtualExperiment",
        on_delete=models.CASCADE,
        related_name="theory_images",
    )
    image = models.ImageField(
        storage=CloudinaryImageStorage(),
        upload_to="theory_images/",
    )
    description = models.CharField(max_length=255, blank=True)

    class Meta:
        db_table = "QuestionBank_theoryimage"
        ordering = ["id"]

    def __str__(self):
        return f"{self.experiment.title} – {self.description or 'Image'}"

    def save(self, *args, **kwargs):
        if self.image:
            self.image.name = self.image.name.replace("\\", "/")
        super().save(*args, **kwargs)

    @cached_property
    def thumb_url(self) -> str:
        if not self.image:
            return ""
        return f"{self.image.url}?f=auto&q=auto&w=400"


class ExperimentStep(models.Model):
    experiment = models.ForeignKey('VirtualExperiment', on_delete=models.CASCADE)
    step_number = models.PositiveIntegerField()
    instruction = CKEditor5Field('Instruction', config_name='default', blank=True, null=True)
    
    image = models.ImageField(
        storage=CloudinaryImageStorage(),
        upload_to='step_images/', 
        blank=True, 
        null=True
    )
    video = models.FileField(
        upload_to='step_videos/', blank=True, null=True,
        storage=VideoCloudinaryStorage()          
    )
    video_url = models.URLField(
        blank=True,
        null=True,
        help_text="Paste a YouTube or Google Drive video link (optional)"
    )

    class Meta:
        db_table = "QuestionBank_experimentstep"
        ordering = ['step_number']

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)


class ExperimentQuestion(models.Model):
    experiment = models.ForeignKey('VirtualExperiment', on_delete=models.CASCADE, related_name='questions')
    question_text = CKEditor5Field('Question Text', config_name='default', blank=True, null=True)
    marks = models.PositiveIntegerField(default=1)

    class Meta:
        db_table = "QuestionBank_experimentquestion"

    def __str__(self):
        return f"Question for {self.experiment.title}"


class ExpectedMeasurement(models.Model):
    experiment = models.ForeignKey(
        "VirtualExperiment",
        on_delete=models.CASCADE,
        related_name="expected_measurements"
    )
    object_name = models.CharField(max_length=120, help_text="e.g. Copper cylinder")
    quantity = models.CharField(max_length=60, help_text="e.g. diameter")
    instrument = models.CharField(max_length=60, default="__any__")
    expected_value = models.CharField(max_length=120, null=True, blank=True)
    expected_unit  = models.CharField(max_length=20, null=True, blank=True)
    tolerance = models.CharField(max_length=20, blank=True, help_text="±5 % or ±0.2 mm")

    marks = models.PositiveSmallIntegerField(default=1)
    required = models.BooleanField(default=True)
    order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        db_table = "QuestionBank_expectedmeasurement"
        unique_together = ("experiment", "object_name", "quantity", "instrument")
        ordering = ["order", "id"]

    def __str__(self):
        return f"{self.object_name} – {self.quantity} ({self.instrument})"


class ExpectedDataAnalysis(models.Model):
    experiment = models.ForeignKey(
        "VirtualExperiment",
        on_delete=models.CASCADE,
        related_name="expected_data_analysis"
    )
    object_name = models.CharField(max_length=120, help_text="e.g. Copper cylinder")
    quantity = models.CharField(max_length=120, help_text="e.g. density, volume, reading error")
    formula_latex = models.TextField(help_text="Enter the formula in LaTeX format, e.g. V = (4/3)πr^3")
    alt_formula_latex = models.TextField(help_text="Optional alternate formula in LaTeX, e.g. V ≈ 1.333 r^3", blank=True, null=True)

    unit = models.CharField(max_length=30, blank=True, null=True)
    marks = models.PositiveSmallIntegerField(default=1)
    order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        db_table = "QuestionBank_expecteddataanalysis"
        ordering = ["order", "id"]

    def __str__(self):
        return f"{self.object_name} – {self.quantity}" 


class DBStoredImage(models.Model):
    name = models.CharField(max_length=255, unique=True)
    content_type = models.CharField(max_length=100)
    data = models.BinaryField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "QuestionBank_dbstoredimage"


class ExperimentDraft(models.Model):
    experiment = models.ForeignKey('VirtualExperiment', on_delete=models.CASCADE)
    student = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)

    observation = models.TextField(blank=True, null=True)
    data = models.JSONField(blank=True, null=True)
    data_analysis = models.TextField(blank=True, null=True, help_text="Saved LaTeX from MathQuill lines")
    image = models.ImageField(upload_to='draft_uploads/', blank=True, null=True)

    created_at = models.DateTimeField(default=timezone.now)
    last_updated = models.DateTimeField(auto_now=True)

    is_active = models.BooleanField(default=True)
    version = models.PositiveIntegerField(default=1)

    class Meta:
        db_table = "QuestionBank_experimentdraft"
        ordering = ['-last_updated']
        unique_together = ('experiment', 'student', 'version')

    def __str__(self):
        return f"Draft v{self.version} (ID {self.id})"


class ExperimentReport(models.Model):
    experiment = models.ForeignKey('VirtualExperiment', on_delete=models.CASCADE)
    student = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)

    group_members = models.TextField("Group Members", help_text="List of group members who participated", blank=True, null=True)
    objective = models.TextField("Objective/Aim", blank=True, null=True)
    theory = models.TextField("Theory/Introduction", blank=True, null=True)
    apparatus_scope = models.TextField("Apparatus/Scope", blank=True, null=True)
    procedure = models.TextField("Procedure/Method", blank=True, null=True)
    results = models.TextField("Results/Raw Data", blank=True, null=True)
    data_analysis = models.TextField("Data & Error Analysis", blank=True, null=True)
    discussion = models.TextField("Discussion", blank=True, null=True)
    conclusion = models.TextField("Conclusion", blank=True, null=True)
    references = models.TextField("References", blank=True, null=True)

    observation = models.TextField("Observation")
    data = models.JSONField("Data Collected", blank=True, null=True)
    is_preliminary_submitted = models.BooleanField(default=False)
    preliminary_submitted_at = models.DateTimeField(null=True, blank=True)

    report_file = models.FileField("Attach Final Report", upload_to='experiment_reports/', blank=True, null=True)

    draft_used = models.OneToOneField(
        'ExperimentDraft',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='final_report',
        help_text="Draft that was used to submit this report, if applicable."
    )

    graph_x_values = models.TextField(
        "X-Axis Values",
        blank=True,
        null=True,
        help_text="Comma-separated list of X values (e.g., 1, 2, 3, 4)"
    )
    graph_y_values = models.TextField(
        "Y-Axis Values",
        blank=True,
        null=True,
        help_text="Comma-separated list of Y values (e.g., 10, 20, 30, 40)"
    )

    submitted_at = models.DateTimeField("Submitted At", null=True, blank=True)

    class Meta:
        db_table = "QuestionBank_experimentreport"

    def __str__(self):
        return f"{self.experiment.title} - {self.student.username}"


UserModel = get_user_model()

class YearReports(UserModel):
    class Meta:
        proxy = True
        verbose_name = "Experiment Reports by Year"
        verbose_name_plural = "Experiment Reports by Year"

class ProgrammeReports(Programme):
    class Meta:
        proxy = True
        verbose_name = "Experiment Report by Programme"
        verbose_name_plural = "Experiment Reports by Programme"    

class ProgrammeExperiment(VirtualExperiment):
    class Meta:
        proxy = True
        verbose_name = "Experiment Group"
        verbose_name_plural = "Experiment Groups"


class ExperimentGraph(models.Model):
    report = models.ForeignKey(
        'ExperimentReport',
        on_delete=models.CASCADE,
        related_name='graphs',
        help_text="The lab report this graph belongs to."
    )

    points_json = models.JSONField(
        default=list,
        blank=True,
        help_text="List of points in the form [{'x': 1, 'y': 2}, ...]"
    )

    vector_json = models.JSONField(
        blank=True,
        null=True,
        help_text="Full Konva stage JSON including freehand drawings"
    )

    title = models.CharField(max_length=255, blank=True, null=True)
    x_label = models.CharField(max_length=100, blank=True, null=True)
    y_label = models.CharField(max_length=100, blank=True, null=True)

    image_snapshot = models.ImageField(
        upload_to='graph_snapshots/',
        blank=True,
        null=True,
        help_text="Optional image snapshot of the graph for preview or AI evaluation."
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "QuestionBank_experimentgraph"

    def __str__(self):
        if self.report:
            return f"Graph #{self.id} for {self.report.student.username} - {self.report.experiment.title}"
        return f"Graph #{self.id}"

    def add_point(self, x, y):
        self.points_json.append({'x': x, 'y': y})
        self.save()

    def clear_points(self):
        self.points_json = []
        self.save()


class ExpectedExperimentGraph(models.Model):
    experiment = models.ForeignKey(
        'VirtualExperiment',
        on_delete=models.CASCADE,
        related_name='expected_graphs'
    )

    title = models.CharField(
        max_length=255,
        help_text="Expected graph title"
    )
    x_quantity = models.CharField(
        max_length=100,
        help_text="Expected X-axis quantity"
    )
    y_quantity = models.CharField(
        max_length=100,
        help_text="Expected Y-axis quantity"
    )
    expected_slope = models.FloatField(
        blank=True, null=True,
        help_text="Expected gradient of the graph"
    )
    slope_tolerance = models.FloatField(
        default=0.2,
        help_text="Allowed fractional deviation (e.g. 0.2 = ±20%)"
    )
    x_unit = models.CharField(max_length=50, blank=True, null=True)
    y_unit = models.CharField(max_length=50, blank=True, null=True)

    expected_trend = models.CharField(
        max_length=50,
        choices=[
            ('linear', 'Linear'),
            ('inverse', 'Inverse'),
            ('quadratic', 'Quadratic'),
            ('constant', 'Constant'),
            ('unknown', 'Unknown'),
        ],
        default='linear'
    )

    min_points = models.PositiveIntegerField(default=5)
    mandatory = models.BooleanField(default=True)

    class Meta:
        db_table = "QuestionBank_expectedexperimentgraph"

    def __str__(self):
        return f"{self.experiment.title} → {self.title}"

    
class ExperimentAnswer(models.Model):
    report = models.ForeignKey(ExperimentReport, on_delete=models.CASCADE, related_name='answers')
    question = models.ForeignKey(ExperimentQuestion, on_delete=models.CASCADE)
    answer_text = models.TextField()

    class Meta:
        db_table = "QuestionBank_experimentanswer"

    def __str__(self):
        return f"Answer by {self.report.student.username} to: {self.question.question_text[:30]}"
    
    
class ReportEvaluation(models.Model):
    report = models.OneToOneField("ExperimentReport", on_delete=models.CASCADE, related_name="evaluation")
    scores = models.JSONField(default=dict)
    feedback = models.JSONField(default=dict)
    evaluator = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    evaluated_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "QuestionBank_reportevaluation"

    def total_score(self):
        if not self.scores:
            return 0
        total = 0
        for v in self.scores.values():
            if isinstance(v, dict):
                total += v.get("rubric", 0)
            elif isinstance(v, (int, float)):
                total += v
        return total

    def __str__(self):
        return f"Evaluation for {self.report.student} - {self.report.experiment}"