import collections
import glob
import re
import os
import tabulate
import pandas as pd
from pathlib import Path

from ..utils.misc import yaml_load

Experiment = collections.namedtuple("Experiment", ["cache", "metric", "param"])


def dict2tuple(dictionary, keys):
    return tuple(dictionary.get(k, None) for k in keys)


def list2tsv(t):
    return "\t".join(str(i) for i in t)


def tsv_table(entries, headers):
    print(list2tsv(headers))
    for entry in entries:
        if isinstance(entry, dict):
            print(list2tsv(dict2tuple(entry, headers)))
        elif isinstance(entry, (list, tuple)):
            print(list2tsv(entry))


class Examiner(object):
    """
    Example usage:
    # Experiment: namedtuple("Experiment", ["cache", "metric", "param"])
    def func(path: pathlib.Path, experiment: Experiment, caches: dict):

        log = latest_log("test", path)
        if log is None:
            return
        experiment.cache["cache1"] = get_cache1(log)
        experiment.metric["metric1"] = get_metric1(log)
        caches["global_cache1"] = get_global_cache1(log)

    examiner = Examiner()
    examiner.add(func)
    examiner.exam("output", "*")
    examiner.table()

    """

    def __init__(self):
        self.exams = set()
        self.caches = {}
        self.experiments = {}

    def add(self, func):
        self.exams.add(func)

    def exam(self, output="output", regex=".*", verbose=False):
        for i, path in enumerate(match_output(output, regex)):
            params = load_params(path)
            if params is None:
                print("No 'params.yaml' found, skip {}".format(path))
                continue
            if verbose:
                print("{}: {}".format(i, path.name))
            if path.name not in self.experiments:
                self.experiments[path.name] = Experiment(cache={}, metric={}, param={})
            self.experiments[path.name].param.update(params)
            for exam in self.exams:
                exam(path, self.experiments[path.name], self.caches)

    def table(self, concise=True, print_tsv=False):
        params = set([(k, v) for experiment in self.experiments.values()
                      for k, v in experiment.param.items() if not re.match("_", k)])
        count = collections.Counter(k for k, _ in params)
        if concise:
            # remove columns with the same values
            param_headers = sorted(k for k, c in count.items() if c > 1)
        else:
            param_headers = sorted(count.keys())

        metric_headers = set()
        for experiment in self.experiments.values():
            metric_headers.update(experiment.metric.keys())
        metric_headers = sorted(metric_headers)

        headers = param_headers + metric_headers
        entries = [[experiment.param.get(h, None) for h in param_headers] +
                   [experiment.metric.get(h, None) for h in metric_headers]
                   for experiment in self.experiments.values()]
        if print_tsv:
            tsv_table(entries, headers)
        return pd.DataFrame(entries, columns=headers)


def match_output(output="output", regex=".*"):
    output = Path(output)
    pattern = re.compile(regex)
    paths = [path for path in output.glob("*") if not path.is_file() and pattern.search(path.name)]
    return paths


def load_params(path):
    param_path = Path(path) / "param"
    if not param_path.exists():
        return None
    params = yaml_load(param_path)
    return params


def latest_log(command, path, index=-1):
    """Get the latest log path of the command"""
    path = Path(path)
    log_paths = sorted(path.glob("log.{}.*".format(command)))
    num_logs = len(log_paths)
    assert isinstance(index, int)
    if index < -num_logs or index > num_logs - 1:
        return None
    return log_paths[index]
