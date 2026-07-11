from pathlib import Path

import environ


def database_settings(database_url, base_dir, connection_max_age=60):
    if not database_url:
        return {
            'default': {
                'ENGINE': 'django.db.backends.sqlite3',
                'NAME': Path(base_dir) / 'db.sqlite3',
            }
        }
    config = environ.Env.db_url_config(database_url)
    if config['ENGINE'] == 'django.db.backends.postgresql':
        config['CONN_MAX_AGE'] = connection_max_age
        config['CONN_HEALTH_CHECKS'] = True
    return {'default': config}
