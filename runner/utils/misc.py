import glob
import os
import json
import re
import collections
import json
import curses
import shlex
import tabulate
import itertools


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
                        for x in components[:-1]]) + components[-1].title()
    else:
        return ''.join(x.title() for x in components)


def entry2str(name, value, str_maxlen, basedir=True):
    name = snake2camel(name, shrink_keep=2)
    if isinstance(value, str):
        if os.path.exists(value) and basedir:
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


def spec2name(spec, str_maxlen, basedir=True):
    keys = list(spec.keys())
    keys.sort()
    strs = [entry2str(key, value, str_maxlen, basedir) for key, value in spec.items()]
    name = '-'.join(strs)
    return name


def shell_arg(value):
    if isinstance(value, str):
        return shlex.quote(value)
    elif isinstance(value, (int, float)):
        return str(value)
    else:
        raise ValueError("{} is not a str, int or float.".format(repr(value)))


def get_shell_arg(spec, param, bool_as_flag=True):
    value = spec[param]
    print(repr(value))
    if bool_as_flag and isinstance(value, bool):
        if value:
            return '--{}'.format(param)
        else:
            return ""
    elif isinstance(value, (str, int, float)):
        return shell_arg(value)
    else:
        raise ValueError("{} is not a str, int, bool or float.".format(repr(value)))


def json_load(filename):
    with open(filename, "r") as fin:
        d = json.load(fin)
    return d


def json_dump(d, filename, sort_keys=True, indent=4):
    with open(filename, "w") as fout:
        json.dump(d, fout, sort_keys=sort_keys, indent=indent)


def color_print(str, color):
    color_map = {
        "RED":     "\x1b[31m",
        "GREEN":   "\x1b[32m",
        "YELLOW":  "\x1b[33m",
        "BLUE":    "\x1b[34m",
        "MAGENTA": "\x1b[35m",
        "CYAN":    "\x1b[36m",
        "WHITE":   "\x1b[37m"
    }
    print(color_map[color.upper()] + str + "\x1b[0m")
