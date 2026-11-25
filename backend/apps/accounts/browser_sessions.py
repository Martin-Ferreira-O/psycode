from django.conf import settings

ACCESS_COOKIE = "psycode_access"
REFRESH_COOKIE = "psycode_refresh"
ACCESS_PATH = "/api/v1/"
REFRESH_PATH = "/api/v1/auth/"


def is_browser_request(request):
    return request.headers.get("X-Psycode-Browser") == "1"


def set_browser_session(response, pair):
    options = {"httponly": True, "secure": not settings.DEBUG, "samesite": "Strict"}
    response.set_cookie(ACCESS_COOKIE, pair["access_token"], path=ACCESS_PATH,
                        max_age=pair["expires_in"], **options)
    response.set_cookie(REFRESH_COOKIE, pair["refresh_token"], path=REFRESH_PATH,
                        max_age=int(settings.SIMPLE_JWT["REFRESH_TOKEN_LIFETIME"].total_seconds()), **options)


def clear_browser_session(response):
    response.delete_cookie(ACCESS_COOKIE, path=ACCESS_PATH, samesite="Strict")
    response.delete_cookie(REFRESH_COOKIE, path=REFRESH_PATH, samesite="Strict")
