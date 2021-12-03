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

    def exam(self, output="output", pattern="*", verbose=False):
        for i, path in enumerate(glob_output(output, pattern)):
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

    # def table_stat(self, metrics, params=None, show_num=False, float_sig=2, fmt="tsv", concise=True):
    #     # filter valid metrics
    #     valid_metrics = set(itertools.chain(exp.metric.keys() for exp in self.experiments.values()))
    #     metrics = list(m for m in metrics if m in valid_metrics)
    #
    #     param2values = self._get_param2values()
    #     param_headers = param2values.keys()
    #     if param_cands is None:
    #         param_cands = []
    #         merged_params = sorted(list(param_headers))
    #     else:
    #         param_cands = set(p for p in param_cands if p in param_headers)
    #         merged_params = set(param_headers) - param_cands
    #         param_cands = list(param_cands)
    #         merged_params = sorted(list(merged_params))
    #     print("Merge {}{}.".format(metric_cands, "" if not param_cands else " with params {}".format(param_cands)))
    #     key2metrics = Key2Values(list)
    #     for experiment in self.experiments.values():
    #         key = tuple(experiment.param.get(p, None) for p in merged_params)
    #         metric = dict((m, experiment.metric[m]) for m in metric_cands if m in experiment.metric)
    #         key2metrics.add(key, metric)
    #
    #     if concise:
    #         # filter out params with the same values for all experiments
    #         merged_param_headers = [p for p in merged_params if len(param2values[p]) > 1]
    #         merged_param_idxs = [i for i, p in enumerate(merged_params) if p in merged_param_headers]
    #     else:
    #         merged_param_headers = merged_params
    #         merged_param_idxs = list(range(len(merged_params)))
    #
    #     if not merged_param_headers:
    #         assert len(key2metrics) == 1
    #         merged_param_headers = ["null"]
    #
    #     if multiple:
    #         headers = list(merged_param_headers)
    #         for m in metric_cands:
    #             if show_num:
    #                 headers.extend([m, "{}_std".format(m), "{}_num".format(m)])
    #             else:
    #                 headers.extend([m, "{}_std".format(m)])
    #     else:
    #         if show_num:
    #             headers = merged_param_headers + ["merge", "merge_std", "merge_num"]
    #         else:
    #             headers = merged_param_headers + ["merge", "merge_std"]
    #
    #     entries = []
    #     for key, metrics in key2metrics.items():
    #         entry = []
    #         if merged_param_idxs:
    #             entry.extend(key[i] for i in merged_param_idxs)
    #         else:
    #             entry.append("null")
    #
    #         if multiple:
    #             for m in metric_cands:
    #                 values = [metric[m] for metric in metrics if m in metric]
    #                 mean, std, num = compute_mean_std_num(values, float_sig)
    #                 if show_num:
    #                     entry.extend([mean, std, num])
    #                 else:
    #                     entry.extend([mean, std])
    #         else:
    #             values = sum(list(metric.values()) for metric in metrics)
    #             mean, std, num = compute_mean_std_num(values, float_sig)
    #             if show_num:
    #                 entry.extend([mean, std, num])
    #             else:
    #                 entry.extend([mean, std])
    #         entries.append(entry)
    #     if fmt == "tsv":
    #         tsv_table(entries, headers)
    #     elif fmt == "md":
    #         print(tabulate.tabulate(entries, headers, "pipe"))
    #     else:
    #         raise ValueError("Unsupported table format: {}".format(repr(fmt)))


def glob_output(output="output", pattern="*"):
    paths = [path for path in glob.glob(os.path.join(output, pattern)) if os.path.isdir(path)]
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
