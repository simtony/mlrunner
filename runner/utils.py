import glob
import os
import json
import re
import collections
import json
import curses
import shlex
import tabulate

RED = "\x1b[31m"
GREEN = "\x1b[32m"
YELLOW = "\x1b[33m"
BLUE = "\x1b[34m"
MAGENTA = "\x1b[35m"
CYAN = "\x1b[36m"
WHITE = "\x1b[37m"


# GPU sorting
def query_gpus():
    """
    return dictionary structure:
    {'0': {'gpu_name'       : 'GeForce RTX 2080 Ti',
           'memory.free'    : 11017,
           'memory.used'    : 1,
           'memory.total'   : 11018,
           'utilization.gpu': 0
           },
     '1': {'gpu_name'       : 'GeForce RTX 2080 Ti',
           'memory.free'    : 11018,
           'memory.used'    : 1,
           'memory.total'   : 11019,
           'utilization.gpu': 0
           }
     }
    """
    query_args = ['index', 'gpu_name', 'memory.free', 'memory.used', 'memory.total', 'utilization.gpu']
    cmd = 'nvidia-smi --query-gpu={} --format=csv,noheader'.format(','.join(query_args))

    def parse(key, value):
        if key in ['memory.free', 'memory.total', 'memory.used']:
            return int(value.upper().strip().replace('MIB', ''))
        elif key == 'utilization.gpu':
            return int(value.replace('%', '').strip())
        else:
            return value.strip()

    gpu_infos = {}
    for info in os.popen(cmd).readlines():
        info_dict = {key: parse(key, value)
                     for key, value in zip(query_args, info.strip().split(','))}
        index = info_dict['index']
        del (info_dict['index'])
        gpu_infos[index] = info_dict
    return gpu_infos


def sort_gpus(gpus, min_mem=None):
    """
    Sort a list of single gpus
    """
    gpus = list(set(gpus))
    gpu_infos = query_gpus()
    if min_mem is not None:
        valid_gpus = [(gpu_infos[gpu]["memory.free"], gpu) for gpu in gpus if
                      gpu_infos[gpu]["memory.free"] > min_mem]
        if not valid_gpus:
            raise ValueError("No GPU with expected memory {} MB.".format(min_mem))

    # fuzzy cmp
    if min_mem is not None:
        gpus.sort(key=lambda x: (not gpu_infos[x]["memory.free"] > min_mem, gpu_infos[x]['utilization.gpu'] // 4))
    else:
        gpus.sort(key=lambda x: (gpu_infos[x]["memory.used"] // 100, gpu_infos[x]['utilization.gpu'] // 4))
    return gpus


# naming
def snake2camel(snake_str, shrink_keep=0):
    """
    "a_snake_case_string" or "a-snake-case-string" to "ASnakeCaseString"
    if shrink_keep > 0, say shrink_keep = 2
    "a_snake_case_string" to "ASnCaString"
    """
    components = snake_str.split('-')
    if len(components) == 1:
        components = components[0].split('_')
    if shrink_keep:
        return ''.join([x[0:shrink_keep].title() if len(x) > shrink_keep else x
                        for x in components]) + components[-1].title()
    else:
        return ''.join(x.title() for x in components)


def entry2str(name, value, str_maxlen, no_shrink_dir=False):
    name = snake2camel(name, shrink_keep=2)
    if isinstance(value, str):
        if os.path.exists(value) and not no_shrink_dir:
            value = os.path.basename(value)
        else:
            # avoid directory split when used as directory name
            value = re.sub("^[/.]*", "", value)  # avoid leading "." and "/"
            value = re.sub("/", "_", value)
        if len(value) > str_maxlen:
            value = value[-str_maxlen:]
    elif isinstance(value, bool):
        if value:
            value = "T"
        else:
            value = "F"
    elif isinstance(value, (float, int)):
        value = "%g" % value
    else:
        value = str(value)
    return name + '_' + value


def param_dict2name(param, str_maxlen, no_shrink_dir=False):
    keys = list(param.keys())
    keys.sort()
    strs = [entry2str(key, value, str_maxlen, no_shrink_dir) for key, value in param.items()]
    name = '-'.join(strs)
    return name


def value2arg(value):
    if isinstance(value, (list, tuple)):
        values = value
    else:
        values = [value]
    command_strs = []
    for value in values:
        if isinstance(value, str):
            command_strs.append(shlex.quote(value))
        elif isinstance(value, (int, float)):
            command_strs.append(str(value))
        else:
            raise ValueError("cmd value {} is not a str, int or float.".format(repr(value)))
    return " ".join(command_strs)


# dict to command line options
def param_dict2command_args(param_dict, bool_as_flag=True):
    args = []
    flags = []
    for key, value in param_dict.items():
        if bool_as_flag and isinstance(value, bool):
            if value:
                flags.append('--{}'.format(key))
        else:
            args.append("--{} {}".format(key, value2arg(value)))
    return ' ' + ' '.join(flags + args) + ' '


def json_load(filename):
    with open(filename, "r") as fin:
        d = json.load(fin)
    return d


def json_dump(d, filename, sort_keys=True, indent=4):
    with open(filename, "w") as fout:
        json.dump(d, fout, sort_keys=sort_keys, indent=indent)


def color_print(str, color):
    print(color + str + "\x1b[0m")


def float_trunc(x, significant=2):
    if x > 1:
        return float(format(x, '.{}f'.format(significant)))
    else:
        return float(format(x, '.{}g'.format(significant)))


def glob_output(output="output", pattern="*"):
    paths = [path for path in glob.glob(os.path.join(output, pattern)) if os.path.isdir(path)]
    return sorted(paths)


def latest_log(command, path, index=-1):
    paths = sorted(glob.glob(os.path.join(path, "log.{}.*".format(command))))
    num_logs = len(paths)
    assert isinstance(index, int)
    if index < -num_logs or index > num_logs - 1:
        return None
    return paths[index]


def load_params(path):
    param_path = os.path.join(path, "param.json")
    if not os.path.exists(param_path):
        return None
    with open(param_path, "r", encoding="utf-8") as fin:
        params = json.load(fin)
    return params


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


def compute_mean_std_num(values, float_sig=2):
    num = len(values)
    if num == 0:
        return 0, 0, 0
    mean = float_trunc(sum(values) / num, float_sig)
    std = float_trunc((sum((v - mean) ** 2 for v in values) / num) ** 0.5, float_sig)
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


Experiment = collections.namedtuple("Experiment", ["cache", "metric", "param"])


class Examiner(object):
    def __init__(self):
        self.exams = {}
        self.caches = {}
        self.experiments = {}

    def reset_all(self):
        self.exams = {}
        self.reset_cache()

    def reset_cache(self):
        self.caches = {}
        self.experiments = {}

    def add_exam(self, key, func):
        self.exams[key] = func

    def examine(self, exam_keys=None, output="output", pattern="*", verbose=False):
        if exam_keys is None:
            exam_keys = self.exams.keys()
        for path in glob_output(output, pattern):
            params = load_params(path)
            if params is None:
                print("No 'params.yaml' found, skip {}".format(path))
                continue
            exp = os.path.basename(path)
            if verbose:
                print(exp)
            if exp in self.experiments:
                experiment = self.experiments[exp]
            else:
                experiment = Experiment(cache={}, metric={}, param={})
            experiment.param.update(params)
            for exam_key in exam_keys:
                self.exams[exam_key](path, experiment, self.caches)
            self.experiments[exp] = experiment

    def _get_param2values(self):
        param2values = Key2Values(set)
        for experiment in self.experiments.values():
            for k, v in experiment.param.items():
                if re.match("_", k):
                    continue
                param2values.add(k, v)
        return param2values

    def tabulate(self, fmt="tsv", concise=True):
        # find unique param values
        param2values = self._get_param2values()
        if concise:
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
        if fmt == "tsv":
            tsv_table(entries, headers)
        elif fmt == "md":
            print(tabulate.tabulate(entries, headers, "pipe"))
        else:
            raise ValueError("Unsupported table format: {}".format(repr(fmt)))

    def tabulate_merge(self, param_cands, metric_cands, multiple=True, fmt="tsv",
                       show_num=False, concise=True, float_sig=2):
        param2values = self._get_param2values()
        param_headers = set(param2values.keys())
        param_cands = set(p for p in param_cands if p in param_headers)
        merged_params = param_headers - param_cands
        param_cands = list(param_cands)
        merged_params = sorted(list(merged_params))

        metric_headers = set()
        for experiment in self.experiments.values():
            metric_headers.update(experiment.metric.keys())
        metric_cands = list(m for m in metric_cands if m in metric_headers)
        if not param_cands:
            print("Empty effective param_cands to merge, skipped.")
            return
        if not metric_cands:
            print("Empty effective metric_cands to merge, skipped.")
            return
        print("Merge metrics {} with the same params {}.".format(metric_cands, param_cands))
        print()

        key2metrics = Key2Values(list)
        for experiment in self.experiments.values():
            key = tuple(experiment.param.get(p, None) for p in merged_params)
            metric = dict((m, experiment.metric[m]) for m in metric_cands if m in experiment.metric)
            key2metrics.add(key, metric)

        if concise:
            # filter out params with the same values for all experiments
            merged_param_headers = [p for p in merged_params if len(param2values[p]) > 1]
            merged_param_idxs = [i for i, p in enumerate(merged_params) if p in merged_param_headers]
        else:
            merged_param_headers = merged_params
            merged_param_idxs = list(range(len(merged_params)))

        if not merged_param_headers:
            assert len(key2metrics) == 1
            merged_param_headers = ["null"]

        if multiple:
            headers = list(merged_param_headers)
            for m in metric_cands:
                if show_num:
                    headers.extend([m, "{}_std".format(m), "{}_num".format(m)])
                else:
                    headers.extend([m, "{}_std".format(m)])
        else:
            if show_num:
                headers = merged_param_headers + ["merge", "merge_std", "merge_num"]
            else:
                headers = merged_param_headers + ["merge", "merge_std"]

        entries = []
        for key, metrics in key2metrics.items():
            entry = []
            if merged_param_idxs:
                entry.extend(key[i] for i in merged_param_idxs)
            else:
                entry.append("null")

            if multiple:
                for m in metric_cands:
                    values = [metric[m] for metric in metrics if m in metric]
                    mean, std, num = compute_mean_std_num(values, float_sig)
                    if show_num:
                        entry.extend([mean, std, num])
                    else:
                        entry.extend([mean, std])
            else:
                values = sum(list(metric.values()) for metric in metrics)
                mean, std, num = compute_mean_std_num(values, float_sig)
                if show_num:
                    entry.extend([mean, std, num])
                else:
                    entry.extend([mean, std])
            entries.append(entry)
        if fmt == "tsv":
            tsv_table(entries, headers)
        elif fmt == "md":
            print(tabulate.tabulate(entries, headers, "pipe"))
        else:
            raise ValueError("Unsupported table format: {}".format(repr(fmt)))
