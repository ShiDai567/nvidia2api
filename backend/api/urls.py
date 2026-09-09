from django.urls import path

from . import admin_views, openai_views

urlpatterns = [
    # OpenAI-compatible
    path("v1/models", openai_views.list_models),
    path("v1/chat/completions", openai_views.chat_completions),

    # Admin
    path("api/admin/login", admin_views.LoginView.as_view()),
    path("api/admin/dashboard", admin_views.DashboardView.as_view()),
    path("api/admin/dashboard/usage", admin_views.DashboardUsageView.as_view()),
    path("api/admin/chat", admin_views.AdminChatView.as_view()),
    path("api/admin/settings", admin_views.SettingsView.as_view()),

    path("api/admin/nvidia-keys", admin_views.NvidiaKeyListView.as_view()),
    path("api/admin/nvidia-keys/import", admin_views.NvidiaKeyImportView.as_view()),
    path("api/admin/nvidia-keys/<int:pk>", admin_views.NvidiaKeyDetailView.as_view()),
    path("api/admin/nvidia-keys/<int:pk>/test", admin_views.NvidiaKeyTestView.as_view()),

    path("api/admin/proxies", admin_views.ProxyListView.as_view()),
    path("api/admin/proxies/import", admin_views.ProxyImportView.as_view()),
    path("api/admin/proxies/<int:pk>", admin_views.ProxyDetailView.as_view()),
    path("api/admin/proxies/<int:pk>/fetch-ip", admin_views.ProxyFetchIpView.as_view()),
    path("api/admin/proxies/check-all", admin_views.ProxyCheckAllView.as_view()),

    path("api/admin/proxy-groups", admin_views.ProxyGroupListView.as_view()),
    path("api/admin/proxy-groups/<int:pk>", admin_views.ProxyGroupDetailView.as_view()),

    path("api/admin/models", admin_views.ModelListView.as_view()),
    path("api/admin/models/sync", admin_views.ModelSyncView.as_view()),
    path("api/admin/models/<int:pk>", admin_views.ModelDetailView.as_view()),

    path("api/admin/api-keys", admin_views.UserApiKeyListView.as_view()),
    path("api/admin/api-keys/<int:pk>", admin_views.UserApiKeyDetailView.as_view()),

    path("api/admin/logs", admin_views.LogListView.as_view()),
]
