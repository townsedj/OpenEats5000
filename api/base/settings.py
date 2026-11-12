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

# Make this unique, and don't share it with anybody.
SECRET_KEY = os.environ.get('DJANGO_SECRET_KEY')
if not SECRET_KEY:
    # No env var, so use a key generated on first run and kept out of git.
    # Deliberately not a literal default: the old 'ChangeMe!' was a known
    # 9-byte value that actually signed the auth tokens.
    # NB: the file is NOT called secrets/ on purpose -- a `secrets` package
    # next to manage.py would shadow the stdlib module of that name.
    _key_file = os.path.join(PROJECT_PATH, '.secret_key')
    try:
        with open(_key_file) as _f:
            SECRET_KEY = _f.read().strip()
    except OSError:
        from django.core.management.utils import get_random_secret_key
        SECRET_KEY = get_random_secret_key()
        with open(_key_file, 'w') as _f:
            _f.write(SECRET_KEY)

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

gettext = lambda s: s
LANGUAGES = (
     ('en', gettext('English')),
     ('de', gettext('German')),
   )

try:
    from local_settings import *
except ImportError:
    pass
