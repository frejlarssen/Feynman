import os

try:
    import constants_local as _constants_local
except ImportError:
    _constants_local = None


def _local_value(name, default=''):
    if _constants_local is None:
        return default

    return getattr(_constants_local, name, default)


BASE_URL = os.environ.get(
    'AIRFLOW_BASE_URL',
    _local_value('BASE_URL', 'http://localhost:8080/api/v2'),
)
AIRFLOW_USERNAME = os.environ.get(
    'AIRFLOW_USERNAME',
    _local_value('AIRFLOW_USERNAME'),
)
AIRFLOW_PASSWORD = os.environ.get(
    'AIRFLOW_PASSWORD',
    _local_value('AIRFLOW_PASSWORD'),
)
AIRFLOW_BEARER_TOKEN = os.environ.get(
    'AIRFLOW_BEARER_TOKEN',
    _local_value('AIRFLOW_BEARER_TOKEN'),
)
AIRFLOW_SESSION_COOKIE = os.environ.get(
    'AIRFLOW_SESSION_COOKIE',
    _local_value('AIRFLOW_SESSION_COOKIE'),
)

DAG_ID = 'feynman'
POOL_ALIAS = {
    'small_pool': 'GPU pool',
    'default_pool': 'CPU pool'
}
