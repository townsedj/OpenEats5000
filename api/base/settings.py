# Django settings for openeats project.
import os, datetime

# We can't set the debug just using the env var.
# Python with evaluate any string as a True bool.
DEBUG = False
if os.environ.get('DJANGO_DEBUG', 'False').lower() == 'true':
    DEBUG = True

SERVE_MEDIA = True

# Build paths inside the project like this: os.path.join(BASE_DIR, ...)
PROJECT_PATH = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# --------------------------------------------------------------- secrets
#
# One mechanism for every secret: an environment variable if it is set,
# otherwise a single-line file beside manage.py that git ignores.
#
# The environment comes first on purpose. This repository is public, so a
# secret inside the working tree is protected by nothing but a .gitignore
# line -- one `git add -f`, one careless `-A` from another tool, and it is
# in a public commit, where it will be scraped within minutes and is
# painful to purge from history. The file exists for the case where setting
# a variable is impractical, such as a service started by something else;
# it is the fallback, not the recommendation.
#
# NB: these are files, not a `secrets/` package. A package of that name
# beside manage.py would shadow the standard library's `secrets` module --
# which is what get_random_secret_key() below imports to do its job.


def _secret(name, filename, generate=None):
    """
    A secret from the environment, else from a gitignored file.

    `generate` is for secrets this app is entitled to invent, which is only
    ever a random value: an API key cannot be generated, so that one has no
    fallback beyond the file and simply comes back empty when absent.
    """
    value = os.environ.get(name)
    if value:
        return value.strip()

    path = os.path.join(PROJECT_PATH, filename)
    try:
        # utf-8-sig, not the platform default: PowerShell's Set-Content
        # writes a UTF-8 BOM on some versions, and read as cp1252 that
        # becomes three visible characters glued to the front of the key.
        # strip() does not remove them, so the result is an authentication
        # failure with a key that looks correct in every editor.
        with open(path, encoding='utf-8-sig') as handle:
            value = handle.read().strip()
            if value:
                return value
    except OSError:
        pass

    if generate is None:
        return None

    value = generate()
    with open(path, 'w') as handle:
        handle.write(value)
    return value


def _new_django_key():
    from django.core.management.utils import get_random_secret_key
    return get_random_secret_key()


# Signs sessions, CSRF and -- because auth is simplejwt sliding tokens --
# the login tokens themselves. Generated on first run rather than defaulting
# to a literal: upstream shipped 'ChangeMe!', a known nine-byte value that
# actually signed the auth tokens, so anyone who had read the OpenEats
# source could forge a login.
SECRET_KEY = _secret('DJANGO_SECRET_KEY', '.secret_key', generate=_new_django_key)

# Force Django to use https headers if its behind a https proxy.
# See: https://docs.djangoproject.com/en/2.0/ref/settings/#secure-proxy-ssl-header
if os.environ.get('HTTP_X_FORWARDED_PROTO', 'False').lower() == 'true':
    SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')

SITE_ID = 1

# SQLite is the local database: one file, no service to run, and a backup is
# a file copy. WAL lets readers and a writer work concurrently, which is all a
# household-sized install needs. IMMEDIATE transactions avoid the "database is
# locked" errors SQLite's deferred default produces under concurrent writes.
DATABASES = {
    'default': {
        'ENGINE': os.environ.get('DATABASE_ENGINE', 'django.db.backends.sqlite3'),
        'NAME': os.environ.get(
            'DATABASE_NAME', os.path.join(PROJECT_PATH, 'openeats.sqlite3')
        ),
        'OPTIONS': {
            'init_command': 'PRAGMA journal_mode=WAL;',
            'transaction_mode': 'IMMEDIATE',
        },
    }
}

# Auto-created primary keys stay AutoField on purpose. The app's models are
# tracked through a git subtree from upstream, and switching to BigAutoField
# would add an AlterField migration to every app for no practical gain here.
DEFAULT_AUTO_FIELD = 'django.db.models.AutoField'

# Hosts/domain names that are valid for this site; required if DEBUG is False
# See https://docs.djangoproject.com/en/2.0/ref/settings/#allowed-hosts
ALLOWED_HOSTS = ['localhost', '127.0.0.1', 'node', 'web']

env_allowed_host = os.environ.get('ALLOWED_HOST', None)
if env_allowed_host is not None:
    if ',' in env_allowed_host:
        ALLOWED_HOSTS += [host.strip() for host in env_allowed_host.split(',')]
    else:
        ALLOWED_HOSTS.append(env_allowed_host)

# List of callables that know how to import templates from various sources.
TEMPLATES = [
    {
        'NAME': 'Core Templates',
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [os.path.join(PROJECT_PATH, 'templates'), ],
        'APP_DIRS': False,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
    {
        'NAME': '3rd Party Templates',
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

MIDDLEWARE = (
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.middleware.locale.LocaleMiddleware',
    'corsheaders.middleware.CorsMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
)

INSTALLED_APPS = (
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.sites',
    'django.contrib.messages',
    'django.contrib.admin',
    'django.contrib.staticfiles',

    'django_filters',
    'rest_framework',
    'rest_framework.authtoken',

    'base',
    'v1.household',
    'v1.nutrition',
    'v1.recipe',
    'v1.recipe_groups',
    'v1.ingredient',
    'v1.list',
    'v1.menu',

    'imagekit',
    'django_extensions',
    'corsheaders'
)

# Password validation
# https://docs.djangoproject.com/en/2.0/topics/auth/passwords/#password-validation
AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]

ROOT_URLCONF = 'base.urls'

WSGI_APPLICATION = 'base.wsgi.application'

# Automatically find the correct time zone to use.
USE_TZ = True

# Language code for this installation. All choices can be found here:
# http://www.i18nguy.com/unicode/language-identifiers.html
LANGUAGE_CODE = 'en-us'

REST_FRAMEWORK = {
    'DEFAULT_FILTER_BACKENDS': ('django_filters.rest_framework.DjangoFilterBackend',),
    'DEFAULT_AUTHENTICATION_CLASSES': (
        'rest_framework_simplejwt.authentication.JWTAuthentication',
        'rest_framework.authentication.SessionAuthentication',
        'rest_framework.authentication.BasicAuthentication',
    ),
    'DEFAULT_PAGINATION_CLASS': 'rest_framework.pagination.LimitOffsetPagination',
    'PAGE_SIZE': 100,
    'DEFAULT_THROTTLE_CLASSES': (
        'rest_framework.throttling.AnonRateThrottle',
    ),
    'DEFAULT_THROTTLE_RATES': {
        'anon': '100/hour',
    }
}

# https://django-rest-framework-simplejwt.readthedocs.io/en/latest/settings.html
# Lifetimes carried over from the old djangorestframework-jwt config. simplejwt
# has no JWT_RESPONSE_PAYLOAD_HANDLER equivalent, so the custom login payload
# is built in v1/accounts/serializers.py instead.
SIMPLE_JWT = {
    # Sliding tokens, not the default access/refresh pair: the front end sends
    # Authorization: JWT <token> and refreshes by POSTing {"token": ...}, which
    # is the sliding shape. See v1/accounts/serializers.py.
    'AUTH_HEADER_TYPES': ('JWT', 'Bearer'),
    'AUTH_TOKEN_CLASSES': ('rest_framework_simplejwt.tokens.SlidingToken',),
    'SLIDING_TOKEN_LIFETIME': datetime.timedelta(days=14),
    'SLIDING_TOKEN_REFRESH_LIFETIME': datetime.timedelta(weeks=30),
}

# We don't want the API to serve static in production.
# So we are forcing the renderer to be JSON only.
if not DEBUG:
    REST_FRAMEWORK['DEFAULT_RENDERER_CLASSES'] = (
        'rest_framework.renderers.JSONRenderer',
    )

# Must be a list of origins *including the scheme*. The old setting name was
# CORS_ORIGIN_WHITELIST and was assigned a parenthesised string rather than a
# tuple, so cors-headers iterated it one character at a time.
CORS_ALLOWED_ORIGINS = ['http://localhost:8080']

env_node_url = os.environ.get('NODE_URL', None)
if env_node_url is not None:
    if ',' in env_node_url:
        CORS_ALLOWED_ORIGINS += [origin.strip() for origin in env_node_url.split(',')]
    else:
        CORS_ALLOWED_ORIGINS.append(env_node_url)

# Static and i18n settings
STATICFILES_FINDERS = (
    'django.contrib.staticfiles.finders.AppDirectoriesFinder',
    'django.contrib.staticfiles.finders.FileSystemFinder',
)

LOCALE_PATHS = (
  os.path.join(PROJECT_PATH, 'locale', ),
)

FIXTURE_DIRS = [
    os.path.join(PROJECT_PATH, 'v1', 'fixtures'),
]

# If you set this to False, Django will make some optimizations so as not
# to load the internationalization machinery.
USE_I18N = True

# Absolute path to the directory that holds media.
# Example: "/home/media/media.lawrence.com/"
MEDIA_ROOT = os.path.join(PROJECT_PATH, 'site-media')
STATIC_ROOT = os.path.join(PROJECT_PATH, 'static-files')

# URL that handles the media served from MEDIA_ROOT. Make sure to use a
# trailing slash if there is a path component (optional in other cases).
# Examples: "http://media.lawrence.com", "http://example.com/media/"
MEDIA_URL = '/site-media/'
STATIC_URL = '/static-files/'

# The assistant. The key is read from the environment and stays here: it is
# never serialised into a response, never written to the repo, and never
# reaches the browser, which is why every assistant feature goes through the
# API rather than calling Anthropic from the front end.
#
#   $env:OPENEATS_AI_KEY = sk-or-v1-...   (PowerShell, this shell only)
#   api/.anthropic_key                     (one line, survives a restart)
#
# Same mechanism as SECRET_KEY above: the environment first, else
# api/.anthropic_key, which git ignores. No generated fallback, because an
# API key cannot be invented -- when it is absent the assistant endpoints
# return 503 and the rest of the app is unaffected.
#
# Whichever provider's key this is, give it a hard spend limit. That is the
# one protection a leaked API key has and the Django key above does not: it
# can be revoked and capped, so a mistake costs a few dollars rather than
# the balance.
ANTHROPIC_API_KEY = _secret('OPENEATS_AI_KEY', '.anthropic_key')

# Which route the assistant takes. One setting rather than two, because the
# endpoint and the model ids have to change together -- OpenRouter rejects
# "claude-haiku-5-5" and Anthropic rejects "anthropic/claude-haiku-5.5", so
# two independent variables are mostly a way to get a confusing 404.
#
# Committed as a default so the app works after a restart with nothing
# exported. These are not secrets; only the key is, and that lives in
# api/.anthropic_key.
#
# OpenRouter exposes an Anthropic-compatible /v1/messages -- an unauthorised
# POST there answers in Anthropic's own error envelope rather than
# OpenRouter's OpenAI-shaped one -- so the official SDK is pointed at it and
# nothing else in the code changes. Same model and the same $0.10/$0.50 per
# MTok as going direct, so the choice is about whose credits are spent.
# The env names are OPENEATS_-prefixed on purpose. ANTHROPIC_* is a shared
# namespace: the SDK reads it, and so does Claude Code, which exports
# ANTHROPIC_BASE_URL=https://api.anthropic.com into every command it runs.
# Reading those names meant an unrelated tool's environment silently
# redirected this app to a provider its key was not for, which looked
# exactly like a bad key. This app's configuration answers to this app.
ANTHROPIC_PROVIDER = (
    os.environ.get('OPENEATS_AI_PROVIDER') or 'openrouter'
).lower()

ANTHROPIC_ROUTES = {
    'anthropic': {
        'base_url': None,
        # Haiku for the high-volume, mechanical work: matching an ingredient
        # line to a USDA food, importing a recipe, estimating a takeaway.
        'match_model': 'claude-haiku-5-5',
        # Week planning is a harder judgement: two sets of targets, one set
        # of meals.
        'plan_model': 'claude-sonnet-5-5',
    },
    'openrouter': {
        'base_url': 'https://openrouter.ai/api',
        'match_model': 'anthropic/claude-haiku-5.5',
        'plan_model': 'anthropic/claude-sonnet-5.5',
    },
}

if ANTHROPIC_PROVIDER not in ANTHROPIC_ROUTES:
    # Loudly, rather than quietly falling back to a route the key is not
    # for: a typo would otherwise look like an authentication problem.
    from django.core.exceptions import ImproperlyConfigured
    raise ImproperlyConfigured(
        'ANTHROPIC_PROVIDER=%r is not one of %s'
        % (ANTHROPIC_PROVIDER, ', '.join(sorted(ANTHROPIC_ROUTES)))
    )

_route = ANTHROPIC_ROUTES[ANTHROPIC_PROVIDER]

# Each still overridable on its own, for trying a different model without
# editing anything.
ANTHROPIC_BASE_URL = (
    os.environ.get('OPENEATS_AI_BASE_URL') or _route['base_url']
)
ANTHROPIC_MATCH_MODEL = (
    os.environ.get('OPENEATS_AI_MATCH_MODEL') or _route['match_model']
)
ANTHROPIC_PLAN_MODEL = (
    os.environ.get('OPENEATS_AI_PLAN_MODEL') or _route['plan_model']
)

gettext = lambda s: s
LANGUAGES = (
     ('en', gettext('English')),
     ('de', gettext('German')),
   )

try:
    from local_settings import *
except ImportError:
    pass
