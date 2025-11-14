from functools import wraps
from django.shortcuts import redirect

def requiere_votante_sesion(view_func):
    @wraps(view_func)
    def _wrapped_view(request, *args, **kwargs):
        if not request.session.get("votante_id"):
            return redirect("login_votante")
        return view_func(request, *args, **kwargs)
    return _wrapped_view
