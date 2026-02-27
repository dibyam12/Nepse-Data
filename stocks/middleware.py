"""
Middleware to track site visits for analytics.
"""
from .models import SiteVisit


class VisitTrackingMiddleware:
    """Records each page visit with session and IP info."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # Skip static files, admin, and API calls
        path = request.path
        skip_prefixes = ('/static/', '/admin/', '/api/', '/favicon.ico')
        if not any(path.startswith(p) for p in skip_prefixes):
            # Ensure session exists
            if not request.session.session_key:
                request.session.create()

            ip = self._get_client_ip(request)
            try:
                SiteVisit.objects.create(
                    session_key=request.session.session_key,
                    ip_address=ip,
                    path=path[:500],
                )
            except Exception:
                pass  # Don't break the site if tracking fails

        return self.get_response(request)

    @staticmethod
    def _get_client_ip(request):
        x_forwarded = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded:
            return x_forwarded.split(',')[0].strip()
        return request.META.get('REMOTE_ADDR')
