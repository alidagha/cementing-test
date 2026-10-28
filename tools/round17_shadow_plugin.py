"""Explicit shadow observer/router. Default serial pytest never loads this plugin."""
from pathlib import Path
import os
import types

import pytest
from _pytest.fixtures import reorder_items
from tools import round17_shadow as evidence


def pytest_addoption(parser):
    group = parser.getgroup('round17-shadow')
    group.addoption('--shadow-role', choices=('collect', 'serial', *evidence.SHARDS))
    group.addoption('--shadow-dir')
    group.addoption('--shadow-manifest')


def pytest_configure(config):
    role = config.getoption('--shadow-role')
    if role is None:
        return
    evidence.require(config.getoption('--shadow-dir'), 'shadow evidence directory required')
    evidence.require(not any(os.environ.get(k) for k in ('PYTEST_ADDOPTS', 'PYTEST_PLUGINS', 'PYTEST_DISABLE_PLUGIN_AUTOLOAD')),
                     'unreviewed pytest environment overrides')
    args = config.invocation_params.args
    for value in args:
        evidence.require(value in ('-p', 'tools.round17_shadow_plugin', '--collect-only', '--durations=0', '--durations-min=0')
                         or value.startswith(('--shadow-role=', '--shadow-dir=', '--shadow-manifest=', '--junitxml=')),
                         'unreviewed pytest selection/options: ' + value)
    for name, plugin in config.pluginmanager.list_name_plugin():
        if plugin is None:
            continue
        module = plugin.__name__ if isinstance(plugin, types.ModuleType) else type(plugin).__module__
        evidence.require(module.startswith('_pytest.') or module in ('anyio.pytest_plugin', __name__),
                         'unrecognized plugin: ' + str(name) + ' / ' + module)
    distributions = {dist.project_name.lower(): dist.version for _, dist in config.pluginmanager.list_plugin_distinfo()}
    evidence.require(distributions == {'anyio': evidence.md.version('anyio')}, 'unexpected plugin distributions')
    config.pluginmanager.register(Observer(config, role), 'round17-shadow-observer')


class Observer:
    def __init__(self, config, role):
        self.config, self.role = config, role
        self.directory = Path(config.getoption('--shadow-dir')).resolve()
        evidence.require(not self.directory.is_relative_to(evidence.ROOT), 'external evidence required')
        self.context = evidence.provenance()
        self.groups = evidence.schedule()
        self.observation = dict(selected=[], routed=[], events=[], warnings=[], collection_errors=[], exitstatus=None)
        self.manifest = None

    def records(self, items):
        records = []
        for item in items:
            module = item.path.resolve().relative_to(evidence.ROOT).as_posix()
            parent = []
            for node in item.listchain():
                if isinstance(node, (pytest.Module, pytest.Class)):
                    parent.append([type(node).__module__ + '.' + type(node).__qualname__, node.nodeid])
            records.append(dict(nodeid=item.nodeid, module=module,
                                collector=[type(item).__module__ + '.' + type(item).__qualname__, parent]))
        return records

    @pytest.hookimpl(wrapper=True, tryfirst=True)
    def pytest_collection_modifyitems(self, session, config, items):
        # Preserve pytest's own scoped-fixture ordering, exactly as in serial.
        # Comparing the pre-hook order directly rejected native reorder_items.
        native_order = self.records(reorder_items(items))
        for hook in config.hook.pytest_collection_modifyitems.get_hookimpls():
            evidence.require(hook.function.__module__.startswith('_pytest.') or hook.function.__module__ == __name__,
                             'unreviewed collection modifier')
        result = yield
        records = self.records(items)
        evidence.require(records == native_order, 'unexpected non-native collection mutation/order')
        self.manifest = dict(schema=1, provenance=self.context, items=records,
                             root_identity_sha256=evidence.digest(evidence.canonical(sorted(r['nodeid'] for r in records))))
        ids = evidence.validate_manifest(self.manifest, self.context, self.groups)
        reference = config.getoption('--shadow-manifest')
        if self.role not in ('collect','serial'):
            evidence.require(reference and evidence.load(reference) == self.manifest, 'full discovery differs from collector')
            selected = [i for i in items if i.nodeid.split('::')[0] in self.groups[self.role]]
            removed = [i for i in items if i.nodeid.split('::')[0] not in self.groups[self.role]]
            self.observation['selected'] = [i.nodeid for i in selected]
            self.observation['routed'] = [i.nodeid for i in removed]
            evidence.require(selected and removed, 'empty/incomplete partition')
            config.hook.pytest_deselected(items=removed)
            items[:] = selected
        else:
            evidence.require(not reference and (self.role == 'serial' or config.option.collectonly), 'collector cannot execute tests or serial cannot route')
            self.observation['selected'] = ids
        evidence.write(self.directory / 'manifest.json', self.manifest)
        return result

    def pytest_collectreport(self, report):
        if report.failed or report.skipped:
            self.observation['collection_errors'].append(report.nodeid)

    def pytest_warning_recorded(self, warning_message, when, nodeid, location):
        self.observation['warnings'].append(dict(category=warning_message.category.__name__, when=when, nodeid=nodeid))

    def pytest_runtest_logreport(self, report):
        self.observation['events'].append(dict(nodeid=report.nodeid, when=report.when,
            outcome=report.outcome, wasxfail=hasattr(report, 'wasxfail')))

    @pytest.hookimpl(trylast=True)
    def pytest_sessionfinish(self, session, exitstatus):
        if self.observation['warnings'] or self.observation['collection_errors'] or self.manifest is None or any(
                e['outcome'] != 'passed' or e['wasxfail'] for e in self.observation['events']):
            session.exitstatus = pytest.ExitCode.TESTS_FAILED
        self.observation['exitstatus'] = int(session.exitstatus)
        evidence.write(self.directory / 'observation.json', self.observation)
