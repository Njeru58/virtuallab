from django.urls import path
from django.urls import path, reverse_lazy
from django.contrib.auth import views as auth_views
from . import views

app_name = 'lab'

urlpatterns = [
    path('', views.lab_home_view, name='home'),
    # Auth Routes (Self-Contained)
    path('dashboard/', views.lab_dashboard_view, name='dashboard'),
    path('login/', views.lab_login_view, name='login'),
    path('register/', views.lab_register_view, name='register'),
    path('logout/', views.lab_logout_view, name='logout'),
    path('activate/<uidb64>/<token>/', views.lab_activate_account, name='activate'),

    # Auth & Password Reset Routes
    path(
        'password-reset/',
        auth_views.PasswordResetView.as_view(
            template_name='virtuallab/auth/password_reset.html',
            subject_template_name='virtuallab/auth/password_reset_subject.txt',
            email_template_name='virtuallab/auth/password_reset_email.txt',  # Plain text fallback
            html_email_template_name='virtuallab/auth/password_reset_email.html',  # Rendered HTML
            success_url=reverse_lazy('lab:password_reset_done'),
            extra_context={'reset_stage': 'reset'},
        ),
        name='password_reset',
    ),

    path(
        'password-reset/done/',
        auth_views.PasswordResetDoneView.as_view(
            template_name='virtuallab/auth/password_reset.html',
            extra_context={'reset_stage': 'done'},
        ),
        name='password_reset_done',
    ),
    path(
        'password-reset-confirm/<uidb64>/<token>/',
        auth_views.PasswordResetConfirmView.as_view(
            template_name='virtuallab/auth/password_reset.html',
            success_url=reverse_lazy('lab:password_reset_complete'),
            extra_context={'reset_stage': 'confirm'},
        ),
        name='password_reset_confirm',
    ),
    path(
        'password-reset-complete/',
        auth_views.PasswordResetCompleteView.as_view(
            template_name='virtuallab/auth/password_reset.html',
            extra_context={'reset_stage': 'complete'},
        ),
        name='password_reset_complete',
    ),

    # Lab Routes
    path('experiments/', views.ExperimentListView.as_view(), name='experiment_list'),
    path('experiment/<int:experiment_id>/', views.experiment_detail, name='experiment_detail'),
    path('experiment/<int:experiment_id>/pdf/', views.report_pdf, name='report_pdf'),
    path('experiment/<int:experiment_id>/submit_report/', views.submit_report, name='submit_report'),
    path('experiment/<int:experiment_id>/submitted/', views.report_submitted, name='report_submitted'),
    path('experiment/<int:experiment_id>/auto_save_draft/', views.auto_save_draft, name='auto_save_draft'),
    path('experiment/<int:experiment_id>/auto_save_report/', views.auto_save_report, name='auto_save_report'),
    path('my-reports/', views.my_evaluated_reports, name='report_list'),
    path('my-reports/<int:report_id>/', views.view_report_detail, name='report_detail'),
    # path('simulations/simple-pendulum/', views.simple_pendulum_lab, name='simple_pendulum_lab'),
]