import collections
import glob
import json
import re
import os
from .utils import table

Experiment = collections.namedtuple("Experiment", ["cache", "metric", "param"])


class Key2Values(object):
    # Group values with the same key
    def __init__(self, group_func=list):
        assert group_func in [list, set]
        self.group_func = group_func
        self.group = collections.defaultdict(group_func)

        # redirect methods
        self.items = self.group.items
        self.keys = self.group.keys
        self.values = self.group.values
        self.get = self.group.get
        self.__contains__ = self.group.__contains__
        self.__delitem__ = self.group.__delitem__
        self.__sizeof__ = self.group.__sizeof__

    def __getitem__(self, item):
        return self.group[item]

    def __setitem__(self, key, value):
        self.group[key] = value

    def __repr__(self):
        return repr(self.group).replace("defaultdict", "Key2Values")

    def __len__(self):
        return len(self.group)

    def add(self, k, v):
        if self.group_func == set:
            if isinstance(v, (list, tuple)):
                self.group[k].update(v)
            else:
                self.group[k].add(v)
        else:
            if isinstance(v, (list, tuple)):
                self.group[k].extend(v)
            else:
                self.group[k].append(v)


class Examiner(object):
    """
    Example usage:

    def func(path, experiment, caches):
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

    def reset(self):
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
            exp = os.path.basename(path)
            if verbose:
                print("{}: {}".format(i, exp))
            if exp in self.experiments:
                experiment = self.experiments[exp]
            else:
                experiment = Experiment(cache={}, metric={}, param={})
            experiment.param.update(params)
            for exam in self.exams:
                exam(path, experiment, self.caches)
            self.experiments[exp] = experiment

    def _get_param2values(self):
        param2values = Key2Values(set)
        for experiment in self.experiments.values():
            for k, v in experiment.param.items():
                if re.match("_", k):
                    continue
                param2values.add(k, v)
        return param2values

    def table(self, tsv=True, concise=True):
        # find unique param values
        param2values = self._get_param2values()
        if concise:
            # remove columns with the same values
            param_headers = sorted(list(k for k, v in param2values.items() if len(v) > 1))
        else:
            param_headers = sorted(list(param2values.keys()))

        metric_headers = set()
        for experiment in self.experiments.values():
            metric_headers.update(experiment.metric.keys())
        metric_headers = sorted(list(metric_headers))
        headers = param_headers + metric_headers
        entries = [[experiment.param.get(h, None) for h in param_headers] +
                   [experiment.metric.get(h, None) for h in metric_headers]
                   for experiment in self.experiments.values()]
        table(entries, headers, tsv)


def match_output(output="output", regex=".*"):
    pattern = re.compile(regex)
    files = [file for file in os.listdir(output) if pattern.search(file)]
    paths = [os.path.join(output, file) for file in files]
    paths = [path for path in paths if os.path.isdir(path)]
    return sorted(paths)


def load_params(path):
    param_path = os.path.join(path, "param.json")
    if not os.path.exists(param_path):
        return None
    with open(param_path, "r", encoding="utf-8") as fin:
        params = json.load(fin)
    return params


def latest_log(command, path, index=-1):
    paths = sorted(glob.glob(os.path.join(path, "log.{}.*".format(command))))
    num_logs = len(paths)
    assert isinstance(index, int)
    if index < -num_logs or index > num_logs - 1:
        return None
    return paths[index]
