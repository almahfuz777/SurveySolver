from pathlib import Path

from django.test import SimpleTestCase

from surveysolver.database import database_settings


class DatabaseSettingsTests(SimpleTestCase):
    def test_empty_url_uses_local_sqlite(self):
        base_dir = Path('C:/workspace/surveysolver')

        configured = database_settings('', base_dir)

        self.assertEqual(
            configured['default'],
            {
                'ENGINE': 'django.db.backends.sqlite3',
                'NAME': base_dir / 'db.sqlite3',
            },
        )

    def test_postgresql_url_enables_persistent_health_checked_connections(self):
        configured = database_settings(
            'postgresql://survey_user@db.example.test:5432/surveysolver',
            Path('.'),
            connection_max_age=120,
        )['default']

        self.assertEqual(configured['ENGINE'], 'django.db.backends.postgresql')
        self.assertEqual(configured['HOST'], 'db.example.test')
        self.assertEqual(configured['PORT'], 5432)
        self.assertEqual(configured['NAME'], 'surveysolver')
        self.assertEqual(configured['CONN_MAX_AGE'], 120)
        self.assertTrue(configured['CONN_HEALTH_CHECKS'])
