from django.contrib import admin
from django.urls import path
from django.conf import settings
from django.conf.urls.static import static
from elecciones import views

urlpatterns = [
    # Login y logout
    path('', views.login_admin, name='home'),
    path('login/', views.login_admin, name='login_admin'),
    path('logout/', views.logout_view, name='logout'),

    # Panel de administración
    path('admin-panel/', views.panel_admin, name='panel_admin'),
    
    # Gestión de usuarios
    path('usuario/agregar/', views.agregar_usuario, name='agregar_usuario'),
    path('usuario/editar/<str:persona_id>/', views.editar_usuario, name='editar_usuario'),

    # CRUD de candidatos y eventos (basados en Persona)
    path('candidato/crear/', views.crear_candidato, name='crear_candidato'),
    path('candidato/editar/<uuid:persona_id>/', views.editar_candidato, name='editar_candidato'),
    path('candidato/desactivar/<str:persona_id>/', views.desactivar_candidato, name='desactivar_candidato'),
    path('evento/<str:evento_id>/asignar-candidatos/', views.asignar_candidatos, name='asignar_candidatos'),
    path('evento/<str:evento_id>/asignar-participantes/', views.asignar_participantes, name='asignar_participantes'),
    path('evento/<str:evento_id>/ver/', views.ver_evento, name='ver_evento'),
    path('evento/crear/', views.crear_evento, name='crear_evento'),
    path('evento/<str:evento_id>/desactivar/', views.desactivar_evento, name='desactivar_evento'),
    path('evento/<str:evento_id>/activar/', views.activar_evento, name='activar_evento'),
    # votante
    path('login-votante/', views.login_votante, name='login_votante'),
    path('panel-usuario/', views.panel_usuario, name='panel_usuario'),
    path('votar-evento/<uuid:evento_id>/', views.votar_evento, name='votar_evento'),
    path('evento/<str:evento_id>/resultados/', views.resultados_evento, name='resultados_evento'),
    path('voto-confirmado/<str:evento_id>/', views.voto_confirmado, name='voto_confirmado'),
    path('voto-status/<str:evento_id>/', views.voto_status, name='voto_status'),
    # Django admin
    path('admin/', admin.site.urls),
]

# Configuración para servir archivos media en desarrollo
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
