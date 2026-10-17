"""Exercise PyPI release selection and issue lifecycle without network writes."""
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import URLError

spec = importlib.util.spec_from_file_location('version_watch', Path(__file__).parents[1] / 'scripts/check_versions.py')
watch = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = watch
spec.loader.exec_module(watch)


def files(*, yanked=False, python='>=3.9'):
    return [{'yanked': yanked, 'requires_python': python}]


class IssueAPI:
    def __init__(self, issues=()):
        self.issues = list(issues)
        self.writes = []

    def request(self, url, method='GET', data=None):
        if method == 'GET':
            return self.issues
        self.writes.append((method, data))
        if method == 'POST':
            self.issues.append({'number': len(self.issues) + 1, 'state': 'open',
                                'user': {'login': 'github-actions[bot]'}, **data})
        else:
            issue = next(i for i in self.issues if i['number'] == int(url.rsplit('/', 1)[1]))
            issue.update(data)
        return self.issues[-1]


class VersionSelection(unittest.TestCase):
    def test_numeric_comparison_instead_of_lexical_sorting(self):
        releases = {'6.9.0': files(), '6.20.3': files(), '6.20.10': files()}
        self.assertEqual(watch.latest_stable(releases), '6.20.10')

    def test_prereleases_yanked_and_unpublished_versions_are_ignored(self):
        releases = {'6.20.3': files(), '7.0.0rc1': files(), '8.0.dev1': files(),
                    '7.0.0': files(yanked=True), '9.0': [], 'not-a-version': files()}
        self.assertEqual(watch.latest_stable(releases), '6.20.3')

    def test_post_releases_are_stable(self):
        self.assertEqual(watch.latest_stable({'1.0': files(), '1.0.post1': files()}), '1.0.post1')

    def test_empty_result_is_an_error_instead_of_up_to_date(self):
        with self.assertRaises(ValueError):
            watch.latest_stable({})

    def test_requirements_must_use_exact_pins(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'requirements.txt'
            path.write_text('# Runtime\ndevpi-server==6.20.3\n')
            self.assertEqual(watch.read_pins(path), {'devpi-server': '6.20.3'})
            path.write_text('devpi-server>=6.10,<7\n')
            with self.assertRaises(ValueError):
                watch.read_pins(path)

    def report(self, releases):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'requirements.txt').write_text('devpi-server==6.20.3\n')
            api = watch.API()
            with patch.object(api, 'request', return_value={'releases': releases}):
                return watch.collect_reports(root, api)[0]

    def test_python_incompatible_release_is_reported_for_manual_migration(self):
        report = self.report({'6.20.3': files(), '7.0.0': files(python='>=99')})
        self.assertTrue(report.needed)
        self.assertFalse(report.compatible)
        self.assertIn('autre version de Python', report.body)

    def test_withdrawn_current_version_opens_an_alert(self):
        report = self.report({'6.20.2': files(), '6.20.3': files(yanked=True)})
        self.assertTrue(report.withdrawn)
        self.assertTrue(report.needed)

    def test_missing_pin_is_an_error(self):
        with self.assertRaises(ValueError):
            self.report({'6.20.4': files()})

    def test_source_failure_cannot_close_existing_issues(self):
        with patch.object(watch, 'collect_reports', side_effect=OSError('PyPI unavailable')), \
             patch.object(watch, 'sync_issues') as sync, \
             patch.object(sys, 'argv', ['check_versions.py', '--write-issues']):
            with self.assertRaises(OSError):
                watch.main()
            sync.assert_not_called()

    def test_failed_issue_creation_is_not_retried(self):
        with patch.object(watch, 'urlopen', side_effect=URLError('response lost')) as request:
            with self.assertRaises(URLError):
                watch.API().request('https://api.github.com/repos/example/repo/issues', 'POST', {})
            self.assertEqual(request.call_count, 1)


class IssueLifecycle(unittest.TestCase):
    def report(self, latest='6.20.4'):
        return watch.Report('devpi-server', '6.20.3', latest, True)

    def test_repeated_checks_create_only_one_issue(self):
        api = IssueAPI()
        for _ in range(3):
            watch.sync_issues(api, 'hallcyn/private-python-registry', [self.report()])
        self.assertEqual(len(api.issues), 1)
        self.assertEqual(len(api.writes), 1)

    def test_new_release_updates_existing_issue(self):
        api = IssueAPI()
        watch.sync_issues(api, 'hallcyn/private-python-registry', [self.report()])
        watch.sync_issues(api, 'hallcyn/private-python-registry', [self.report('7.0.0')])
        self.assertEqual(len(api.issues), 1)
        self.assertIn('7.0.0', api.issues[0]['title'])

    def test_updated_repository_closes_issue_and_rollback_reopens_it(self):
        api = IssueAPI()
        watch.sync_issues(api, 'hallcyn/private-python-registry', [self.report()])
        watch.sync_issues(api, 'hallcyn/private-python-registry', [self.report('6.20.3')])
        self.assertEqual(api.issues[0]['state'], 'closed')
        watch.sync_issues(api, 'hallcyn/private-python-registry', [self.report()])
        self.assertEqual(api.issues[0]['state'], 'open')
        self.assertEqual(len(api.issues), 1)

    def test_not_planned_suppresses_only_that_release(self):
        api = IssueAPI()
        watch.sync_issues(api, 'hallcyn/private-python-registry', [self.report()])
        api.issues[0].update(state='closed', state_reason='not_planned')
        watch.sync_issues(api, 'hallcyn/private-python-registry', [self.report()])
        self.assertEqual(len(api.writes), 1)
        watch.sync_issues(api, 'hallcyn/private-python-registry', [self.report('7.0.0')])
        self.assertEqual(len(api.issues), 2)

    def test_manual_issues_are_not_modified(self):
        report = self.report()
        api = IssueAPI([{'number': 1, 'user': {'login': 'human'}, 'state': 'open',
                         'title': report.title, 'body': report.body}])
        watch.sync_issues(api, 'hallcyn/private-python-registry', [report])
        self.assertEqual(len(api.issues), 2)
        self.assertEqual(api.writes[0][0], 'POST')


if __name__ == '__main__':
    unittest.main()
