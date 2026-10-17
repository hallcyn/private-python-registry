#!/usr/bin/env python3
"""Check pinned devpi versions against PyPI, without deploying or updating code."""
import argparse
from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from packaging.requirements import Requirement
from packaging.specifiers import SpecifierSet
from packaging.utils import canonicalize_name
from packaging.version import InvalidVersion, Version

GITHUB = 'https://api.github.com'


class API:
    def __init__(self, token=None):
        self.token = token

    def request(self, url, method='GET', data=None):
        headers = {'User-Agent': 'hallcyn-private-python-registry-version-watch', 'Accept': 'application/json'}
        if urlparse(url).hostname == 'api.github.com':
            headers.update({'Accept': 'application/vnd.github+json', 'X-GitHub-Api-Version': '2022-11-28'})
            if self.token:
                headers['Authorization'] = f'Bearer {self.token}'
        body = None if data is None else json.dumps(data).encode()
        if body is not None:
            headers['Content-Type'] = 'application/json'
        for attempt in range(3):
            try:
                with urlopen(Request(url, data=body, headers=headers, method=method), timeout=30) as response:
                    return json.load(response)
            except HTTPError as error:
                if method != 'GET' or error.code not in (429, 500, 502, 503, 504) or attempt == 2:
                    raise
            except (URLError, TimeoutError):
                if method != 'GET' or attempt == 2:
                    raise
            time.sleep(2 ** attempt)


def read_pins(path):
    pins = {}
    for line in path.read_text().splitlines():
        line = line.split('#', 1)[0].strip()
        if not line:
            continue
        req = Requirement(line)
        specs = list(req.specifier)
        if req.url or req.marker or req.extras or len(specs) != 1 or specs[0].operator != '==':
            raise ValueError(f'An exact runtime pin is required: {line}')
        pins[canonicalize_name(req.name)] = str(Version(specs[0].version))
    if not pins:
        raise ValueError('No runtime pins found')
    return pins


def latest_stable(releases):
    candidates = []
    for name, files in releases.items():
        try:
            parsed = Version(name)
        except InvalidVersion:
            continue
        if not parsed.is_prerelease and not parsed.is_devrelease and any(not f.get('yanked') for f in files):
            candidates.append((parsed, name))
    if not candidates:
        raise ValueError('PyPI returned no published stable releases')
    return max(candidates)[1]


@dataclass(frozen=True)
class Report:
    package: str
    current: str
    latest: str
    compatible: bool
    withdrawn: bool = False

    @property
    def needed(self):
        return Version(self.latest) > Version(self.current) or self.withdrawn

    @property
    def marker(self):
        return f'<!-- dependency-update:{self.package} -->'

    @property
    def target_marker(self):
        return f'<!-- dependency-version:{self.latest} -->'

    @property
    def title(self):
        return f'[Mise à jour] {self.package} : {self.current} → {self.latest}'

    @property
    def body(self):
        compatibility = ('Les métadonnées PyPI autorisent la version Python du moniteur ; la CI Docker doit encore valider la pile complète.'
                         if self.compatible else 'La nouvelle version nécessite une autre version de Python : étudier cette migration avant de modifier le pin.')
        withdrawn = '\n**La version actuellement fixée a été retirée (yanked) de PyPI.**\n' if self.withdrawn else ''
        return f'''{self.marker}
{self.target_marker}
## Mise à jour à examiner

| Dépendance | Version du dépôt | Dernière version stable |
| --- | --- | --- |
| {self.package} | `{self.current}` | `{self.latest}` |

{compatibility}
{withdrawn}
Source : https://pypi.org/project/{self.package}/{self.latest}/

- [ ] Lire les notes de version et vérifier la compatibilité devpi-server / devpi-web / devpi-client.
- [ ] Mettre à jour `requirements.txt` sur une branche de travail.
- [ ] Attendre la réussite de la CI : construction, thème, authentification, publication, installation et persistance.
- [ ] Sauvegarder le volume `/data` avant un éventuel déploiement et vérifier les migrations requises.

Cette issue est gérée par la CI ; conserver les échanges dans les commentaires.
Fermer comme « not planned » ignore cette version précise. Une version ultérieure
peut créer une nouvelle alerte. Aucune mise à jour ni aucun déploiement n’est automatique.
'''


def collect_reports(root, api):
    python = '.'.join(map(str, sys.version_info[:3]))
    reports = []
    for package, current in read_pins(root / 'requirements.txt').items():
        releases = api.request(f'https://pypi.org/pypi/{package}/json')['releases']
        if not releases.get(current):
            raise ValueError(f'Pinned version {package}=={current} is missing from PyPI')
        latest = latest_stable(releases)
        files = [f for f in releases[latest] if not f.get('yanked')]
        compatible = any(SpecifierSet(f.get('requires_python') or '').contains(python) for f in files)
        withdrawn = all(f.get('yanked', False) for f in releases[current])
        reports.append(Report(package, current, latest, compatible, withdrawn))
    # Finish all API reads before changing any issue, including closing an old one.
    return reports


def sync_issues(api, repository, reports):
    base = f'{GITHUB}/repos/{repository}/issues'
    issues = []
    for page in range(1, 21):
        batch = api.request(f'{base}?state=all&per_page=100&page={page}')
        issues.extend(i for i in batch if 'pull_request' not in i
                      and i.get('user', {}).get('login') == 'github-actions[bot]')
        if len(batch) < 100:
            break
    else:
        raise ValueError('Issue pagination limit reached; refusing possible duplicates')
    for report in reports:
        matching = [i for i in issues if report.marker in (i.get('body') or '')]
        opened = [i for i in matching if i['state'] == 'open']
        if not report.needed:
            for issue in opened:
                api.request(f'{base}/{issue["number"]}', 'PATCH', {'state': 'closed', 'state_reason': 'completed'})
            continue
        payload = {'title': report.title, 'body': report.body}
        if opened:
            issue = opened[0]
            if issue['title'] != report.title or issue['body'] != report.body:
                api.request(f'{base}/{issue["number"]}', 'PATCH', payload)
            continue
        previous = next((i for i in matching if report.target_marker in (i.get('body') or '')), None)
        if previous:
            if previous.get('state_reason') != 'not_planned':
                api.request(f'{base}/{previous["number"]}', 'PATCH', {**payload, 'state': 'open'})
            continue
        api.request(base, 'POST', payload)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--write-issues', action='store_true')
    args = parser.parse_args()
    api = API(os.environ.get('GITHUB_TOKEN'))
    reports = collect_reports(Path(__file__).resolve().parents[1], api)
    summary = '# Versions devpi\n\n| Dépendance | Dépôt | Stable publiée | Action |\n| --- | --- | --- | --- |\n'
    for r in reports:
        summary += f'| {r.package} | {r.current} | {r.latest} | {"À examiner" if r.needed else "À jour"} |\n'
    print(summary)
    if os.environ.get('GITHUB_STEP_SUMMARY'):
        with open(os.environ['GITHUB_STEP_SUMMARY'], 'a') as stream:
            stream.write(summary)
    if args.write_issues:
        repository = os.environ.get('GITHUB_REPOSITORY', '')
        if not re.fullmatch(r'[\w.-]+/[\w.-]+', repository) or not api.token:
            raise ValueError('GITHUB_REPOSITORY and GITHUB_TOKEN are required to write issues')
        sync_issues(api, repository, reports)


if __name__ == '__main__':
    main()
