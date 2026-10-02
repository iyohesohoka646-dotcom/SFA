"""Bounded cumulative control evidence. Predicates and iterators stay untouched."""
from __future__ import annotations

import contextvars
import time
from contextlib import contextmanager


class ControlCollector:
    def __init__(self, session, *, detail_limit=512, node_limit=4096, publish_interval=.1):
        self.session = session
        self.detail_limit, self.node_limit = detail_limit, node_limit
        self.interval = publish_interval
        self.summaries = {}
        self.details = []
        self.omitted = 0
        self.revision = 0
        self.failed = False
        self._sent_details = 0
        self._dirty = set()
        self._last_publish = time.monotonic()
        self._ticks = 0
        self._activation = contextvars.ContextVar('control_activation', default=('main', None))
        self._activation_counts = contextvars.ContextVar('control_activation_counts', default=None)
        self._loops = contextvars.ContextVar('control_loops', default=())

    def record(self, ref, kind):
        key = ref['node_id']
        if key not in self.summaries:
            if len(self.summaries) >= self.node_limit:
                self.failed = True
                return None
            self.summaries[key] = dict(node_id=key, kind=kind, source=ref['source'], true_count=0, false_count=0,
                body_entries=0, activations=0, natural_exits=0, break_exits=0, nonlocal_exits=0,
                exception_exits=0, complete=False, revision=0, activation_samples=[], omitted_activations=0)
        self._dirty.add(key)
        return self.summaries[key]

    def detail(self, ref, kind, **fields):
        if len(self.details) < self.detail_limit:
            activation, parent = self._activation.get()
            self.details.append(dict(node_id=ref['node_id'], kind=kind,
                activation_id=activation, parent_activation_id=parent, **fields))
        else:
            self.omitted += 1

    def tick(self):
        self._ticks += 1
        # No per-iteration serialization or transport writes on the hot path.
        if self._ticks % 128 == 0 and time.monotonic() - self._last_publish >= self.interval:
            self.flush()

    def count_activation(self, ref, key):
        counts = self._activation_counts.get()
        if counts is not None:
            values = counts.setdefault(ref['node_id'], {})
            values[key] = values.get(key, 0) + 1

    def branch(self, ref, selected):
        try:
            summary = self.record(ref, 'branch')
            if summary is None:
                return
            summary['true_count' if selected else 'false_count'] += 1
            self.count_activation(ref, 'true_count' if selected else 'false_count')
            self.detail(ref, 'branch', selected=selected)
            self.tick()
        except Exception:
            # Observer errors cannot replace the user's result or exception.
            self.failed = True

    @contextmanager
    def activation(self, label, activation_id):
        parent = self._activation.get()[0]
        token = self._activation.set((activation_id, parent))
        counts = {}
        count_token = self._activation_counts.set(counts)
        try:
            yield
        finally:
            for node_id, values in counts.items():
                summary = self.summaries.get(node_id)
                if summary is not None:
                    if len(summary['activation_samples']) < 16:
                        defaults = {key: 0 for key in ('true_count', 'false_count', 'body_entries', 'activations', 'natural_exits', 'break_exits', 'nonlocal_exits', 'exception_exits')}
                        summary['activation_samples'].append({'activation_id': activation_id,
                            'parent_activation_id': parent, **defaults, **values})
                    else:
                        summary['omitted_activations'] += 1
                    self._dirty.add(node_id)
            self._activation_counts.reset(count_token)
            self._activation.reset(token)

    @contextmanager
    def loop(self, ref):
        state = {'ref': ref, 'natural': False, 'reached_after': False, 'entries': 0}
        try:
            summary = self.record(ref, 'loop')
        except Exception:
            summary = None
            self.failed = True
        if summary is not None:
            summary['activations'] += 1
            self.count_activation(ref, 'activations')
        token = self._loops.set((*self._loops.get(), state))
        error = False
        try:
            yield
        except BaseException:
            error = True
            raise
        finally:
            self._loops.reset(token)
            try:
                outcome = 'exception_exits' if error else 'natural_exits' if state['natural'] else 'break_exits' if state['reached_after'] else 'nonlocal_exits'
                if summary is not None:
                    summary[outcome] += 1
                    self.count_activation(ref, outcome)
                    self._dirty.add(ref['node_id'])
                self.detail(ref, 'loop_exit', outcome=outcome, entries=state['entries'])
                self.tick()
            except Exception:
                self.failed = True

    def iteration(self, ref):
        try:
            state = self._loops.get()[-1]
            state['entries'] += 1
            summary = self.record(ref, 'loop')
            if summary is not None:
                summary['body_entries'] += 1
                self.count_activation(ref, 'body_entries')
            self.detail(ref, 'iteration', iteration=state['entries'])
            self.tick()
        except Exception:
            self.failed = True

    def natural(self, ref):
        try:
            self._loops.get()[-1]['natural'] = True
        except Exception:
            self.failed = True

    def reached_after(self, ref):
        try:
            self._loops.get()[-1]['reached_after'] = True
        except Exception:
            self.failed = True

    def flush(self, *, final=False):
        try:
            self.revision += 1
            keys = list(self.summaries) if final else sorted(self._dirty)
            for offset in range(0, len(keys), 16):
                values = []
                for key in keys[offset:offset + 16]:
                    summary = self.summaries[key]
                    summary.update(revision=self.revision, complete=final and not self.failed)
                    values.append(dict(summary))
                self.session.emit('control.summary', {'summaries': values, 'final': final, 'omitted': self.omitted}, critical=False)
            # Details are emitted only once, at most 512. Summaries remain cumulative.
            if self._sent_details < len(self.details) or final:
                fresh = self.details[self._sent_details:]
                for offset in range(0, max(1, len(fresh)), 128):
                    self.session.emit('control.details', {'details': fresh[offset:offset + 128], 'omitted': self.omitted}, critical=False)
                self._sent_details = len(self.details)
            if final:
                self.session.emit('control.finished', {'node_count': len(self.summaries), 'revision': self.revision,
                    'complete': not self.failed, 'omitted': self.omitted}, critical=True)
            self._dirty.clear()
            self._last_publish = time.monotonic()
        except Exception:
            self.failed = True
