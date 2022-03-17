import collections
import glob
import re
import os
import tabulate
from ..utils.misc import yaml_load

Experiment = collections.namedtuple("Experiment", ["cache", "metric", "param"])


def trunc(x, significant=2):
    if x > 1:
        return float(format(x, '.{}f'.format(significant)))
    else:
        return float(format(x, '.{}g'.format(significant)))


def dict2tuple(dictionary, keys):
    return tuple(dictionary.get(k, None) for k in keys)


def list2tsv(t):
    return "\t".join(str(i) for i in t)


def table(entries, headers, tsv=True):
    if tsv:
        print(list2tsv(headers))
        for entry in entries:
            if isinstance(entry, dict):
                print(list2tsv(dict2tuple(entry, headers)))
            elif isinstance(entry, (list, tuple)):
                print(list2tsv(entry))
    else:
        print(tabulate.tabulate(entries, headers, "pipe"))


def compute_mean_std_num(values, float_sig=2):
    num = len(values)
    if num == 0:
        return 0, 0, 0
    mean = trunc(sum(values) / num, float_sig)
    std = trunc((sum((v - mean) ** 2 for v in values) / num) ** 0.5, float_sig)
    return mean, std, num


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

    def table(self, tsv=True, concise=True, raw=False):
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
        if raw:
            return entries, headers


def match_output(output="output", regex=".*"):
    pattern = re.compile(regex)
    files = [file for file in os.listdir(output) if pattern.search(file)]
    paths = [os.path.join(output, file) for file in files]
    paths = [path for path in paths if os.path.isdir(path)]
    return sorted(paths)


def load_params(path):
    param_path = os.path.join(path, "param")
    if not os.path.exists(param_path):
        return None
    params = yaml_load(param_path)
    return params


def latest_log(command, path, index=-1):
    paths = sorted(glob.glob(os.path.join(path, "log.{}.*".format(command))))
    num_logs = len(paths)
    assert isinstance(index, int)
    if index < -num_logs or index > num_logs - 1:
        return None
    return paths[index]
