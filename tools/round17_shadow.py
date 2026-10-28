"""Opt-in Round17 shadow evidence CLI; never imports application/test code itself."""
import argparse
from collections import Counter
from copy import deepcopy
import hashlib
import importlib.metadata as md
import json
import math
import os
from pathlib import Path
import platform
import re
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ('tools/round17_shadow.py', 'tools/round17_shadow_plugin.py', 'tools/round17_shadow_schedule.json')
SCHEDULE_SHA = 'c185a884ec51059468440666c621b7afedad2b90a06b2ef12e257a4ace3e73d7'
# Fixed reviewed baseline identities, not a future test-count acceptance threshold.
BASELINE_ROOTS = '4639129d9f11427fea3bfefdedf28590412511e75ddd97a9d38e3413af2f512b'
BASELINE_PROTECTED = '0bf884932475e9704d568dfef07a0e9ec33eb5ecbe1ffe180346e013ac028432'
BASELINE_WORKFLOW = '90d3b2e5578fbe4913f859413370d010c44577a00f42f8ae21b457f71166f79a'
PACKAGES = ('pytest', 'streamlit', 'pandas', 'numpy', 'pyarrow', 'docxtpl', 'python-docx', 'Jinja2', 'matplotlib')


def require(condition, message):
    if not condition:
        raise ValueError(message)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode()


def load(path):
    return json.loads(Path(path).read_text())


def write(path, data):
    Path(path).write_bytes(canonical(data) + b'\n')


def schedule():
    raw = (ROOT / TOOLS[2]).read_bytes()
    require(digest(raw) == SCHEDULE_SHA, 'approved schedule checksum drift')
    s = json.loads(raw)
    require(set(s['shards']) == {'A', 'B'}, 'missing/extra shard')
    groups = {k: v['modules'] for k, v in s['shards'].items()}
    flat = sum(groups.values(), [])
    require(flat and len(flat) == len(set(flat)), 'duplicate/overlapping schedule modules')
    for path in flat:
        require(re.fullmatch(r'(?:tests/)?test_[a-zA-Z0-9_]+\.py', path), 'ambiguous module path')
    return groups


def provenance():
    git = lambda *args: subprocess.check_output(['git', *args], cwd=ROOT, text=True).strip()
    head = git('rev-parse', 'HEAD')
    expected = os.environ.get('SHADOW_EXPECTED_SHA', head)
    require(head == expected and re.fullmatch('[0-9a-f]{40}', head), 'wrong checkout SHA')
    paths = set(git('ls-files').splitlines()) | set(TOOLS)
    untracked = set(git('ls-files', '--others', '--exclude-standard').splitlines())
    require(untracked <= set(TOOLS), 'unexpected untracked source inputs')
    files = {}
    for name in sorted(paths):
        path = ROOT / name
        require(path.is_file() and not path.is_symlink(), 'missing/symlink source: ' + name)
        files[name] = digest(path.read_bytes())
    protected = {k: v for k, v in files.items() if k not in TOOLS and k != '.github/workflows/regression.yml'}
    require(digest(canonical(protected)) == BASELINE_PROTECTED, 'protected source/test/template/policy drift')
    require(digest((ROOT / '.github/workflows/regression.yml').read_bytes()[:8874]) == BASELINE_WORKFLOW,
            'original serial workflow prefix drift')
    hosted = os.environ.get('GITHUB_ACTIONS') == 'true'
    run = os.environ.get('GITHUB_RUN_ID', 'local')
    attempt = os.environ.get('GITHUB_RUN_ATTEMPT', 'local')
    require(not hosted or all(re.fullmatch('[1-9][0-9]*', x) for x in (run, attempt)), 'invalid hosted run identity')
    packages = {x: md.version(x) for x in PACKAGES}
    require(packages['pytest'] == '9.1.1' and sys.version_info[:2] == (3, 12), 'unsupported Python/pytest')
    for line in (ROOT / 'requirements.txt').read_text().splitlines():
        if '==' in line and not line.lstrip().startswith('#'):
            name, version = line.split('==')
            require(md.version(name) == version, 'pinned environment drift: ' + name)
    return dict(checkout_sha=head, github_run_id=run, github_run_attempt=attempt,
                runner_os=os.environ.get('RUNNER_OS', platform.system()),
                runner_arch=os.environ.get('RUNNER_ARCH', platform.machine()), python=sys.version,
                packages=packages, source=files, schedule_sha256=SCHEDULE_SHA,
                baseline_root_identity_sha256=BASELINE_ROOTS,
                plugin_distributions={'anyio': md.version('anyio')},
                environment_limitations='Serial metadata does not attest all transitive packages, locale or runner image.')


def validate_manifest(manifest, expected, groups):
    require(type(manifest['schema']) is int and manifest['schema'] == 1 and manifest['provenance'] == expected, 'manifest provenance/schema drift')
    records = manifest['items']
    ids = [r['nodeid'] for r in records]
    require(ids and len(ids) == len(set(ids)), 'empty/duplicate root identities')
    require(digest(canonical(sorted(ids))) == manifest['root_identity_sha256'], 'root identity checksum')
    require(manifest['root_identity_sha256'] == expected['baseline_root_identity_sha256'], 'baseline root additions/deletions/renames')
    owned = sum(groups.values(), [])
    require(len(owned) == len(set(owned)), 'overlapping module assignment')
    for r in records:
        require(r['module'] in owned and r['nodeid'].startswith(r['module'] + '::') and r['collector'] and r['collector'][0] in ('_pytest.python.Function', '_pytest.unittest.TestCaseFunction'),
                'unknown module/collector')
        require(r['module'] == r['nodeid'].split('::')[0], 'ambiguous root module')
    require({r['module'] for r in records} == set(owned), 'missing/new module')
    return ids


def xml_identity(nodeid):
    path, bracket, parameters = nodeid.partition('[')
    parts = path.split('::')
    parts[0] = re.sub(r'\.py$', '', parts[0].replace('/', '.'))
    parts[-1] += bracket + parameters
    return '.'.join(parts[:-1]), parts[-1]


def validate_log_environment(log, expected):
    require(re.findall(r'^plugins:.*$', log, re.M) == [
        'plugins: anyio-' + expected['plugin_distributions']['anyio']], 'plugin log/environment contradiction')
    require(re.search(r'^platform .+ -- Python ' + re.escape(expected['python'].split()[0]) +
                      r', pytest-9\.1\.1, pluggy-[^\s]+$', log, re.M), 'Python log/environment contradiction')


def parse_result(directory, full_ids, selected, routed):
    """Independent JUnit/log reconciliation, retaining pytest subtest event multiplicity."""
    root = ET.parse(directory / 'junit.xml').getroot()
    suites = [root] if root.tag == 'testsuite' else root.findall('testsuite') if root.tag == 'testsuites' else []
    cases = [c for s in suites for c in s.findall('testcase')]
    require(suites and cases and len(cases) == len(list(root.iter('testcase'))), 'missing/misplaced XML cases')
    identities = [(c.get('classname'), c.get('name')) for c in cases]
    require(all(all(x) for x in identities) and len(set(identities)) == len(identities), 'duplicate/empty XML identity')
    mapping = {xml_identity(n): n for n in full_ids}
    require(len(mapping) == len(full_ids), 'ambiguous native XML mapping')
    require(all(i in mapping for i in identities), 'unknown XML testcase')
    order = [mapping[i] for i in identities]
    require(order == selected, 'XML executed identities/order differ')
    require(not any(int(s.attrib[k]) for s in suites for k in ('failures', 'errors', 'skipped'))
            and not any(e.tag in ('failure', 'error', 'skipped') for e in root.iter()), 'failed/errored/skipped XML')
    require(all(math.isfinite(float(c.attrib['time'])) and float(c.attrib['time']) >= 0 for c in cases), 'invalid XML time')
    log = (directory / 'certification.log').read_text()
    lines = log.rstrip().splitlines()
    collection = f'collected {len(full_ids)} items'
    if routed:
        collection += f' / {len(routed)} deselected / {len(selected)} selected'
    require([l for l in lines if l.startswith('collected ')] == [collection], 'collection/selection log mismatch')
    suffix = f'{len(selected)} passed' + (f', {len(routed)} deselected' if routed else '')
    require(re.fullmatch(r'=+ ' + re.escape(suffix) + r' in [0-9]+(?:\.[0-9]+)?s(?: \([^)]+\))? =+', lines[-1]),
            'missing/contradictory success marker')
    require(sum(bool(re.match(r'=+ [0-9]+ (?:passed|failed|errors?|skipped|xfailed|xpassed)\b', l)) for l in lines) == 1,
            'repeated terminal summary')
    require(re.search(r'\bpytest-9\.1\.1\b', log) and not re.search(
        r'^=+\s*(?:warnings summary|FAILURES|ERRORS|short test summary info)\s*=+$', log, re.M | re.I), 'warning/failure/unsupported log')
    headers = [i for i, l in enumerate(lines) if re.fullmatch(r'=+ slowest durations =+', l)]
    require(len(headers) == 1, 'missing/repeated durations report')
    phases = {k: Counter() for k in ('setup', 'call', 'teardown')}
    for line in lines[headers[0] + 1:-1]:
        if not line.strip():
            continue
        match = re.fullmatch(r'\s*[0-9]+(?:\.[0-9]+)?s\s+(setup|call|teardown)\s+(.+)', line)
        require(match is not None, 'unrecognized duration grammar')
        phases[match[1]][match[2]] += 1
    require(all(set(phases[k]) == set(selected) for k in phases), 'missing/extra execution phase roots')
    require(all(n == 1 for k in ('setup', 'teardown') for n in phases[k].values()), 'duplicate setup/teardown')
    require(sum(int(s.attrib['tests']) for s in suites) == sum(phases['call'].values()), 'suite/call events disagree')
    return phases


def check_bundle(directory, expected, groups, role):
    directory = Path(directory)
    names = {'manifest.json', 'metadata.json', 'observation.json', 'process.json', 'certification.log'}
    if role != 'collect':
        names.add('junit.xml')
    sums = load(directory / 'checksums.json')
    require(set(sums) == names and {p.name for p in directory.iterdir()} == names | {'checksums.json'}, 'missing/extra evidence files')
    for name in names:
        path = directory / name
        require(path.is_file() and not path.is_symlink() and path.stat().st_size and digest(path.read_bytes()) == sums[name],
                'empty/corrupt evidence: ' + name)
    metadata = load(directory / 'metadata.json')
    instance = metadata.pop('runner_instance')
    require(set(instance) == {'name', 'host'} and all(isinstance(v, str) and v for v in instance.values()), 'missing runner identity')
    require(metadata == dict(expected, role=role), 'wrong source/environment/run/role')
    manifest = load(directory / 'manifest.json')
    ids = validate_manifest(manifest, expected, groups)
    observation = load(directory / 'observation.json')
    selected = ids if role == 'collect' else [n for n in ids if n.split('::')[0] in groups[role]]
    selected_set = set(selected)
    routed = [] if role == 'collect' else [n for n in ids if n not in selected_set]
    require(selected and observation['selected'] == selected and observation['routed'] == routed, 'selection/order/partition drift')
    require(observation['warnings'] == [] and observation['collection_errors'] == [] and type(observation['exitstatus']) is int and observation['exitstatus'] == 0,
            'warning/error/incomplete execution')
    process = load(directory / 'process.json')
    require(process == {'pytest_exit': 0, 'evidence_complete': True} and type(process['pytest_exit']) is int
            and process['evidence_complete'] is True, 'nonzero/incomplete process')
    events = observation['events']
    validate_log_environment((directory / 'certification.log').read_text(), expected)
    if role == 'collect':
        require(not events, 'collector executed tests')
        log = (directory / 'certification.log').read_text()
        lines = log.rstrip().splitlines()
        require([l for l in lines if l.startswith('collected ')] == [f'collected {len(ids)} items']
                and re.fullmatch(r'=+ ' + str(len(ids)) + r' tests collected in [0-9]+(?:\.[0-9]+)?s(?: \([^)]+\))? =+', lines[-1]),
                'incomplete collector log')
        require(re.search(r'\bpytest-9\.1\.1\b', log) and not re.search(
            r'^=+\s*(?:warnings summary|FAILURES|ERRORS|short test summary info)\s*=+$', log, re.M | re.I),
            'collector warning/error/unsupported log')
        return manifest, None
    phases = parse_result(directory, ids, selected, routed)
    counts = {k: Counter() for k in phases}
    event_order = []
    for e in events:
        require(e['nodeid'] in selected and e['when'] in counts and e['outcome'] == 'passed' and e['wasxfail'] is False, 'bad execution report')
        counts[e['when']][e['nodeid']] += 1
        if not event_order or event_order[-1] != e['nodeid']:
            event_order.append(e['nodeid'])
    require(counts == phases and event_order == selected, 'observed/log execution mismatch/order')
    for n in selected:
        sequence = [e['when'] for e in events if e['nodeid'] == n]
        require(sequence[0] == 'setup' and sequence[-1] == 'teardown' and all(x == 'call' for x in sequence[1:-1]), 'invalid phase order')
    return manifest, phases


def compare(serial, collection, shards, expected, groups, jobs):
    require(set(jobs) == {'regression', 'shadow-collection', 'shadow-modules'} and
            all(v['result'] == 'success' for v in jobs.values()), 'missing/failed/empty dependency jobs')
    manifest, _ = check_bundle(collection, expected, groups, 'collect')
    ids = [r['nodeid'] for r in manifest['items']]
    require(set(shards) == {'A', 'B'}, 'partial/empty matrix')
    serial = Path(serial)
    require({p.name for p in serial.iterdir()} == {'junit.xml', 'certification.log', 'metadata.json'}, 'missing/extra serial artifact')
    for p in serial.iterdir():
        require(p.is_file() and not p.is_symlink() and p.stat().st_size, 'empty serial artifact')
    metadata = load(serial / 'metadata.json')
    for key in ('checkout_sha', 'github_run_id', 'github_run_attempt', 'runner_os', 'runner_arch', 'python', 'packages'):
        require(metadata.get(key) == expected[key], 'serial provenance mismatch: ' + key)
    serial_log = (serial / 'certification.log').read_text()
    validate_log_environment(serial_log, expected)
    reference = parse_result(serial, ids, ids, [])
    instances = [load(Path(shards[k]) / 'metadata.json')['runner_instance'] for k in ('A', 'B')]
    require(instances[0] != instances[1], 'shards do not identify independent runners')
    executed = set()
    for role in ('A', 'B'):
        other, phases = check_bundle(shards[role], expected, groups, role)
        require(other == manifest, 'shard full discovery differs')
        own = set(phases['call'])
        require(not executed & own, 'overlapping executed shards')
        executed |= own
        for k in phases:
            require(phases[k] == Counter({n: reference[k][n] for n in own}), 'serial/shadow phase or subtest mismatch')
    require(executed == set(ids), 'execution union gap')
    return {'status': 'EXPERIMENTAL_PARITY_ONLY', 'roots': len(ids), 'serial_call_reports': sum(reference['call'].values()),
            'checkout_sha': expected['checkout_sha'], 'limitations': expected['environment_limitations']}


def run(role, directory, reference):
    directory = Path(directory).resolve()
    require(not directory.is_relative_to(ROOT) and not directory.exists(), 'evidence must use a new external directory')
    directory.mkdir(parents=True)
    context = provenance()
    write(directory / 'metadata.json', dict(context, role=role, runner_instance={
        'name': os.environ.get('RUNNER_NAME', 'local'), 'host': platform.node()}))
    command = [sys.executable, '-B', '-m', 'pytest', '-p', 'tools.round17_shadow_plugin',
               '--shadow-role=' + role, '--shadow-dir=' + str(directory)]
    if role == 'collect':
        command.append('--collect-only')
    else:
        require(reference, 'missing full discovery manifest')
        command += ['--shadow-manifest=' + str(Path(reference).resolve()), '--durations=0', '--durations-min=0',
                    '--junitxml=' + str(directory / 'junit.xml')]
    with (directory / 'certification.log').open('wb') as log:
        process = subprocess.Popen(command, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        for block in iter(lambda: process.stdout.read(65536), b''):
            log.write(block)
            log.flush()
            sys.stdout.buffer.write(block)
            sys.stdout.buffer.flush()
        code = process.wait()
    write(directory / 'process.json', {'pytest_exit': code, 'evidence_complete': code == 0})
    names = ['manifest.json', 'metadata.json', 'observation.json', 'process.json', 'certification.log']
    if role != 'collect':
        names.append('junit.xml')
    existing = {n: digest((directory / n).read_bytes()) for n in names if (directory / n).is_file()}
    write(directory / 'checksums.json', existing)
    if code:
        return code
    check_bundle(directory, context, schedule(), role)
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    r = sub.add_parser('run')
    r.add_argument('--role', required=True, choices=['collect', 'A', 'B'])
    r.add_argument('--directory', required=True)
    r.add_argument('--reference')
    c = sub.add_parser('compare')
    for n in ('serial', 'collection', 'A', 'B', 'output'):
        c.add_argument('--' + n, required=True)
    sub.add_parser('self-test')
    args = parser.parse_args()
    if args.command == 'run':
        return run(args.role, args.directory, args.reference)
    if args.command == 'compare':
        require(os.environ.get('GITHUB_ACTIONS') == 'true', 'hosted comparator requires actual run context')
        result = compare(args.serial, args.collection, {'A': args.A, 'B': args.B}, provenance(), schedule(),
                         json.loads(os.environ['SHADOW_NEEDS_JSON']))
        write(args.output, result)
        print(json.dumps(result))
        return 0
    return self_test()


# Synthetic self-check implementation follows; its evidence never represents product execution.

def self_test():
    """Disposable synthetic evidence only; no project data, pytest, solver or Word run."""
    results = []
    ids = ['tests/test_synthetic_a.py::test_one[α]', 'tests/test_synthetic_a.py::test_two',
           'tests/test_synthetic_b.py::Case::test_three', 'tests/test_synthetic_b.py::test_four']
    groups = {'A': ['tests/test_synthetic_a.py'], 'B': ['tests/test_synthetic_b.py']}
    expected = dict(checkout_sha='a' * 40, github_run_id='123', github_run_attempt='1',
        runner_os='Linux', runner_arch='X64', python='3.12.15 (synthetic fixture)', packages={'pytest': '9.1.1'},
        source={'synthetic-only': 'b' * 64}, schedule_sha256='c' * 64,
        baseline_root_identity_sha256=digest(canonical(sorted(ids))), plugin_distributions={'anyio': '1.0'},
        environment_limitations='synthetic self-check, no product execution')
    manifest = dict(schema=1, provenance=expected, root_identity_sha256=expected['baseline_root_identity_sha256'],
        items=[dict(nodeid=n, module=n.split('::')[0], collector=['_pytest.python.Function', []]) for n in ids])
    jobs = {k: {'result': 'success'} for k in ('regression', 'shadow-collection', 'shadow-modules')}

    def seal(path):
        write(path / 'checksums.json', {f.name: digest(f.read_bytes()) for f in path.iterdir() if f.name != 'checksums.json'})

    def fixture(base, subtests):
        for role in ('serial', 'collect', 'A', 'B'):
            d = base / role
            d.mkdir()
            selected = ids if role in ('serial', 'collect') else [n for n in ids if n.split('::')[0] in groups[role]]
            routed = [n for n in ids if n not in selected]
            meta = {k: expected[k] for k in ('checkout_sha', 'github_run_id', 'github_run_attempt', 'runner_os', 'runner_arch', 'python', 'packages')}
            write(d / 'metadata.json', meta if role == 'serial' else dict(expected, role=role, runner_instance={'name': role, 'host': 'synthetic-' + role}))
            events = []
            for n in selected if role != 'collect' else []:
                events.append(dict(nodeid=n, when='setup', outcome='passed', wasxfail=False))
                events.extend(dict(nodeid=n, when='call', outcome='passed', wasxfail=False)
                              for _ in range(3 if subtests and n == ids[0] else 1))
                events.append(dict(nodeid=n, when='teardown', outcome='passed', wasxfail=False))
            collection_line = f'collected {len(ids)} items'
            summary = f'{len(selected)} passed'
            if routed:
                collection_line += f' / {len(routed)} deselected / {len(selected)} selected'
                summary += f', {len(routed)} deselected'
            log = 'platform linux -- Python 3.12.15, pytest-9.1.1, pluggy-1.7.0\nplugins: anyio-1.0\n' + collection_line + '\n'
            if role != 'collect':
                root = ET.Element('testsuites')
                suite = ET.SubElement(root, 'testsuite', tests=str(sum(e['when'] == 'call' for e in events)), failures='0', errors='0', skipped='0')
                for n in selected:
                    cls, name = xml_identity(n)
                    ET.SubElement(suite, 'testcase', classname=cls, name=name, time='0')
                ET.ElementTree(root).write(d / 'junit.xml')
                log += '================ slowest durations ================\n'
                log += ''.join('0.00s ' + e['when'] + ' ' + e['nodeid'] + '\n' for e in events)
                log += '================ ' + summary + ' in 0.01s ================\n'
            else:
                log += f'================ {len(ids)} tests collected in 0.01s ================\n'
            (d / 'certification.log').write_text(log)
            if role != 'serial':
                write(d / 'manifest.json', manifest)
                write(d / 'observation.json', dict(selected=selected, routed=routed, events=events, warnings=[], collection_errors=[], exitstatus=0))
                write(d / 'process.json', dict(pytest_exit=0, evidence_complete=True))
                seal(d)

    def mutate_json(path, fn):
        value = load(path)
        fn(value)
        write(path, value)

    mutations = []
    def add(name, action, reseal=None):
        mutations.append((name, action, reseal))
    for tag in ('failure', 'error', 'skipped'):
        def bad_xml(b, tag=tag):
            path = b / 'A/junit.xml'; t = ET.parse(path); ET.SubElement(next(t.getroot().iter('testcase')), tag); t.write(path)
        add('XML ' + tag, bad_xml, 'A')
    def xml_change(b, fn):
        path = b / 'A/junit.xml'; t = ET.parse(path); fn(t.getroot().find('testsuite')); t.write(path)
    add('delete XML case', lambda b: xml_change(b, lambda s: s.remove(s[0])), 'A')
    add('duplicate XML case', lambda b: xml_change(b, lambda s: s.append(deepcopy(s[0]))), 'A')
    add('wrong XML order', lambda b: xml_change(b, lambda s: s.__setitem__(slice(None), list(reversed(s)))), 'A')
    add('wrong XML identity', lambda b: xml_change(b, lambda s: s[0].set('name', 'wrong')), 'A')
    for value in ('-1', 'nonsense', '999999'):
        add('invalid suite count ' + value, lambda b, v=value: xml_change(b, lambda s: s.set('tests', v)), 'A')
    add('nonfinite XML time', lambda b: xml_change(b, lambda s: s[0].set('time', 'nan')), 'A')
    add('truncated XML', lambda b: (b / 'A/junit.xml').write_text('<testsuites>'), 'A')
    def replace_log(b, old, new, role='A'):
        path = b / role / 'certification.log'; path.write_text(path.read_text().replace(old, new))
    add('wrong collected count', lambda b: replace_log(b, 'collected 4 items', 'collected 5 items'), 'A')
    add('wrong terminal passed', lambda b: replace_log(b, '2 passed,', '3 passed,'), 'A')
    add('truncated terminal', lambda b: replace_log(b, 'in 0.01s', 'unfinished'), 'A')
    add('missing durations', lambda b: replace_log(b, 'slowest durations', 'other heading'), 'A')
    add('unexpected phase grammar', lambda b: replace_log(b, '0.00s setup', '0.00s other'), 'A')
    add('pytest warning summary', lambda b: replace_log(b, 'pytest-9.1.1', 'pytest-9.1.1\n==== warnings summary ===='), 'A')
    add('pytest warning terminal', lambda b: replace_log(b, '2 passed, 2 deselected', '2 passed, 2 deselected, 1 warning'), 'A')
    add('unknown pytest version', lambda b: replace_log(b, 'pytest-9.1.1', 'pytest-8.0'), 'A')
    add('truncated collector log', lambda b: replace_log(b, 'tests collected in 0.01s', 'unfinished', 'collect'), 'collect')
    add('shadow plugin log drift', lambda b: replace_log(b, 'anyio-1.0', 'anyio-2.0'), 'A')
    add('collector Python log drift', lambda b: replace_log(b, 'Python 3.12.15', 'Python 3.11.0', 'collect'), 'collect')
    add('serial plugin drift', lambda b: replace_log(b, 'anyio-1.0', 'anyio-2.0', 'serial'))
    for key in ('checkout_sha', 'github_run_id', 'github_run_attempt', 'python', 'runner_os', 'runner_arch', 'packages'):
        add('serial wrong ' + key, lambda b, k=key: mutate_json(b / 'serial/metadata.json', lambda x: x.update({k: 'wrong'})))
    for key in ('role', 'source', 'schedule_sha256', 'github_run_attempt'):
        add('shadow wrong ' + key, lambda b, k=key: mutate_json(b / 'A/metadata.json', lambda x: x.update({k: 'wrong'})), 'A')
    for outcome in ('failed', 'skipped'):
        add('observer ' + outcome, lambda b, v=outcome: mutate_json(b / 'A/observation.json', lambda x: x['events'][0].update(outcome=v)), 'A')
    add('observer xfail', lambda b: mutate_json(b / 'A/observation.json', lambda x: x['events'][0].update(wasxfail=True)), 'A')
    add('invalid phase order', lambda b: mutate_json(b / 'A/observation.json', lambda x: x['events'].insert(0, x['events'].pop())), 'A')
    add('missing call event', lambda b: mutate_json(b / 'A/observation.json', lambda x: x['events'].pop(1)), 'A')
    add('duplicate setup event', lambda b: mutate_json(b / 'A/observation.json', lambda x: x['events'].insert(0, deepcopy(x['events'][0]))), 'A')
    add('observer warning', lambda b: mutate_json(b / 'A/observation.json', lambda x: x['warnings'].append('warning')), 'A')
    add('collection failure', lambda b: mutate_json(b / 'collect/observation.json', lambda x: x['collection_errors'].append('error')), 'collect')
    add('collector executed tests', lambda b: mutate_json(b / 'collect/observation.json', lambda x: x['events'].append('execution')), 'collect')
    def redistribute_calls(b):
        d = b / 'A'; observation = load(d / 'observation.json')
        events = []
        for n, count in zip(ids[:2], (1, 3)):
            events.append(dict(nodeid=n, when='setup', outcome='passed', wasxfail=False))
            events.extend(dict(nodeid=n, when='call', outcome='passed', wasxfail=False) for _ in range(count))
            events.append(dict(nodeid=n, when='teardown', outcome='passed', wasxfail=False))
        observation['events'] = events; write(d / 'observation.json', observation)
        log = (d / 'certification.log').read_text(); head, rest = log.split('================ slowest durations ================\n')
        terminal = rest.rstrip().splitlines()[-1]
        (d / 'certification.log').write_text(head + '================ slowest durations ================\n' +
            ''.join('0.00s ' + e['when'] + ' ' + e['nodeid'] + '\n' for e in events) + terminal + '\n')
    add('wrong per-parent subtest distribution', redistribute_calls, 'A')
    add('nonzero process', lambda b: mutate_json(b / 'A/process.json', lambda x: x.update(pytest_exit=7)), 'A')
    add('wrong selected order', lambda b: mutate_json(b / 'A/observation.json', lambda x: x['selected'].reverse()), 'A')
    add('routing gap', lambda b: mutate_json(b / 'A/observation.json', lambda x: x['routed'].pop()), 'A')
    add('routing overlap', lambda b: mutate_json(b / 'A/observation.json', lambda x: x['routed'].append(x['selected'][0])), 'A')
    add('root rename', lambda b: mutate_json(b / 'A/manifest.json', lambda x: x['items'][0].update(nodeid='tests/test_synthetic_a.py::renamed')), 'A')
    add('module drift', lambda b: mutate_json(b / 'A/manifest.json', lambda x: x['items'][0].update(module='tests/test_new.py')), 'A')
    add('duplicate manifest root', lambda b: mutate_json(b / 'A/manifest.json', lambda x: x['items'].append(deepcopy(x['items'][0]))), 'A')
    add('collector identity drift', lambda b: mutate_json(b / 'A/manifest.json', lambda x: x['items'][0].update(collector=['wrong'])), 'A')
    add('missing artifact', lambda b: (b / 'A/junit.xml').unlink())
    add('missing serial metadata', lambda b: (b / 'serial/metadata.json').unlink())
    add('empty evidence', lambda b: (b / 'A/junit.xml').write_bytes(b''), 'A')
    add('bad checksum', lambda b: mutate_json(b / 'A/checksums.json', lambda x: x.update({'junit.xml': 'bad'})))
    add('corrupt JSON', lambda b: (b / 'A/observation.json').write_text('{'), 'A')
    with tempfile.TemporaryDirectory(prefix='round17-shadow-selfcheck-') as temp:
        base = Path(temp)
        for subtests in (False, True):
            d = base / ('subtests' if subtests else 'normal'); d.mkdir(); fixture(d, subtests)
            result = compare(d / 'serial', d / 'collect', {k: d / k for k in groups}, expected, groups, jobs)
            results.append(dict(case=d.name, expected='ACCEPT', actual='ACCEPT', result=result))
        for i, (name, action, reseal) in enumerate(mutations):
            d = base / str(i); d.mkdir(); fixture(d, True); action(d)
            if reseal:
                seal(d / reseal)
            try:
                compare(d / 'serial', d / 'collect', {k: d / k for k in groups}, expected, groups, jobs)
            except (ValueError, KeyError, TypeError, IndexError, OSError, ET.ParseError) as error:
                results.append(dict(case=name, expected='REJECT', actual='REJECT', reason=str(error)))
            else:
                raise AssertionError('unsafe acceptance: ' + name)
        for name, altered_jobs, altered_shards, altered_groups in (
            ('missing job', {}, {'A': base / 'normal/A', 'B': base / 'normal/B'}, groups),
            ('failed job', {**jobs, 'shadow-modules': {'result': 'failure'}}, {'A': base / 'normal/A', 'B': base / 'normal/B'}, groups),
            ('partial matrix', jobs, {'A': base / 'normal/A'}, groups),
            ('empty matrix', jobs, {}, groups),
            ('overlap assignment', jobs, {'A': base / 'normal/A', 'B': base / 'normal/B'}, {'A': groups['A'], 'B': groups['A']}),
            ('missing assigned module', jobs, {'A': base / 'normal/A', 'B': base / 'normal/B'}, {'A': [], 'B': groups['B']})):
            try:
                compare(base / 'normal/serial', base / 'normal/collect', altered_shards, expected, altered_groups, altered_jobs)
            except (ValueError, KeyError) as error:
                results.append(dict(case=name, expected='REJECT', actual='REJECT', reason=str(error)))
            else:
                raise AssertionError('unsafe acceptance: ' + name)
    print(json.dumps(results, indent=2, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    sys.exit(main())
