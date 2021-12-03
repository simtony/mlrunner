import collections
import glob
import json
import re
import os
import tabulate


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
