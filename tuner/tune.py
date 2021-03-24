# -*- coding: utf-8 -*-
import asyncio
import argparse
import yaml
import random
import itertools
import re
import types
import copy
import sys
import os
import shutil
from datetime import datetime
from tuner.utils import param_dict2name, param_dict2command_args, json_load, json_dump, color_print, RED, GREEN


def run(coro):
    if sys.version_info >= (3, 7):
        return asyncio.run(coro)

    # Emulate asyncio.run() on older versions

    # asyncio.run() requires a coroutine, so require it here as well
    if not isinstance(coro, types.CoroutineType):
        raise TypeError("run() requires a coroutine object")

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()
        asyncio.set_event_loop(None)


def sweep(param2choices, num_sample=None):
    # random combination of param choices
    for key, values in param2choices.items():
        assert isinstance(values, list), "{} should be a list, not {}".format(key, type(values))

    param_choices = [[(key, value) for value in values] for key, values in param2choices.items()]
    cand_params = [list(param) for param in itertools.product(*param_choices)]
    if num_sample is not None:
        random.shuffle(cand_params)
        params = cand_params[:num_sample]
        params.sort()
    else:
        params = cand_params
    param_dicts = [dict(param) for param in params]
    return param_dicts


def build_tasks(args):
    # parse yaml file
    with open(args.config, "r") as fin:
        docs = list(yaml.load_all(fin, Loader=yaml.FullLoader))
    assert len(docs) > 1, "Empty yaml file."
    config = docs[0]

    def safe_load(key, data_type, required=False):
        value = data_type()
        if required:
            assert key in config, "Invalid yaml format: '{}' should be in the first doc.".format(key)
        if key in config:
            value = config[key]
            if value:
                assert isinstance(value, data_type), \
                    "Invalid yaml format: '{}' should be a {}.".format(key, data_type)
        return value

    name2template = safe_load("template", dict, required=True)
    assert name2template, "No command templates."
    if args.command:
        assert args.command in name2template, \
            "command={} is not in valid commands {}".format(args.command, tuple(name2template.keys()))
    resources = [str(i) for i in safe_load("resource", list, required=True)]
    defaults = safe_load("default", dict)
    aliases = safe_load("alias", dict)
    if aliases:
        for key, value in aliases.items():
            assert isinstance(value, (list, dict)), \
                "Invalid yaml format: '{}' in 'alias' should be a list or dict.".format(key)

    def safe_alias(key, value):
        if key in aliases:
            if isinstance(aliases[key], list):
                # param replacement
                return {new_key: value for new_key in aliases[key]}
            if isinstance(aliases[key], dict):
                # param remap
                assert value in aliases[key], \
                    "value of '{}' should be in {}".format(key, tuple(aliases[key].keys()))
                return aliases[key][value]
        else:
            return {key: value}

    choices = docs[1:]
    if args.param_choices is not None:
        choices.extend(yaml.load_all(args.param_choices, Loader=yaml.FullLoader))
    assert len(choices) > 0, "Invalid yaml format: no param choices available."

    # build task commands and de-duplication
    datetime_str = datetime.now().strftime("%Y-%m-%d.%H:%M:%S")
    uniq_param_dicts = []
    orphan_param_keys = set()
    tasks = []
    stats = dict()
    for param_dict in itertools.chain.from_iterable(sweep(choice, num_sample=args.sample) for choice in choices):
        # prepare param_dict
        name = param_dict2name(param_dict, str_maxlen=100, no_shrink_dir=args.no_shrink_dir)
        for key, value in defaults.items():
            if key not in param_dict:
                param_dict[key] = value
        if param_dict in uniq_param_dicts:
            continue
        else:
            uniq_param_dicts.append(copy.deepcopy(param_dict))
        param_keys = set(param_dict.keys())
        param_dict["_name"] = name
        if args.no_param_dir:
            param_dict["_output"] = args.output
        else:
            param_dict["_output"] = os.path.join(args.output, name)
        param_dict["_datetime"] = datetime_str

        # prepare command
        name2command = {}
        for name, command_template in name2template.items():
            if args.command is not None and args.command != name:
                continue
            empty_params = []
            command = command_template
            for curly_param in re.findall(r"{[\w-]+?}", command):
                param = curly_param.strip("{}")
                if param in param_keys:
                    param_keys.remove(param)
                if param in param_dict:
                    s = str(param_dict[param])
                    command = command.replace(curly_param, s)
                else:
                    empty_params.append(curly_param)
            for square_param in re.findall(r"\[[\w-]+?\]", command):
                param = square_param.strip("[]")
                if param in param_keys:
                    param_keys.remove(param)
                if param in param_dict:
                    s = param_dict2command_args(safe_alias(param, param_dict[param]), bool_as_flag=True)
                    command = command.replace(square_param, s)
                else:
                    empty_params.append(square_param)

            assert not empty_params, "params {} are not specified in 'default' or 'param_choice'".format(empty_params)
            command = " ".join(command.split())
            if args.no_param_dir:
                log_file = "log.{}.{}.{}".format(name, param_dict["_datetime"], param_dict["_name"])
            else:
                log_file = "log.{}.{}".format(name, param_dict["_datetime"])
            log_path = os.path.join(param_dict["_output"], log_file)

            if args.debug:
                suffix = "2>&1 | tee {}".format(log_path)
            else:
                suffix = "> {} 2>&1".format(log_path)
            name2command[name] = command + " " + suffix
        orphan_param_keys.update(param_keys)
        stat = {key: {"code": -1} for key in name2command.keys()}
        if not args.force:
            stat_path = os.path.join(param_dict["_output"], "stat.json")
            if os.path.exists(stat_path):
                o_stat = json_load(stat_path)
                for key in stat.keys():
                    if key in o_stat and o_stat[key]["code"] == 0:
                        stat[key]["code"] = 0
        tasks.append(dict(param=param_dict, command=name2command))
        stats[param_dict["_name"]] = stat
    if args.debug:
        tasks = tasks[:1]
        stats = {tasks[0]["param"]["_name"]: {key: {"code": -1} for key in tasks[0]["command"].keys()}}
    return resources, tasks, stats, orphan_param_keys


async def build_worker(tasks, queue, stats, resource):
    while True:
        index = await queue.get()
        param_dict = tasks[index]["param"]
        name2command = tasks[index]["command"]
        stat = stats[param_dict["_name"]]
        prefix = "CUDA_VISIBLE_DEVICES={}".format(resource)
        os.makedirs(param_dict["_output"], exist_ok=True)
        for key, command in name2command.items():
            name2command[key] = " ".join([prefix, command])
        param_dict["_commands"] = name2command

        # dump param into json
        param_path = os.path.join(param_dict["_output"], "param.json")
        if os.path.exists(param_path):
            o_param_dict = json_load(param_path)
            for key, value in param_dict.items():
                # don't overwrite old commands
                if key == "_commands":
                    o_param_dict[key].update(param_dict[key])
                else:
                    o_param_dict[key] = param_dict[key]
        else:
            o_param_dict = param_dict
        json_dump(o_param_dict, param_path)

        for key, command in name2command.items():
            info = "{:5}:{:2d}/{:2d}, {}".format(key, index, queue.maxsize, param_dict["_output"])
            if stat[key]["code"] == 0:
                print("SKIP " + info)
                continue
            stat[key]["gpu"] = resource

            process = await asyncio.create_subprocess_shell(command)
            info = "gpu: {}, ".format(resource) + info
            print("START   " + info)
            await process.wait()

            returncode = process.returncode
            stat_path = os.path.join(param_dict["_output"], "stat.json")
            if os.path.exists(stat_path):
                o_stat = json_load(stat_path)
                o_stat.update(stat)
            else:
                o_stat = stat
            try:
                if returncode != 0:
                    stats[param_dict["_name"]][key]["code"] = 1
                    o_stat[key]["code"] = 1
                    color_print("FAIL    " + info, RED)
                    break
                else:
                    stats[param_dict["_name"]][key]["code"] = 0
                    o_stat[key]["code"] = 0

                    color_print("SUCCEED " + info, GREEN)
            except Exception as e:
                print(e, type(e))
            json_dump(o_stat, stat_path, indent=None)
        queue.task_done()


async def run_all(tasks, stats, resources):
    # populate the task queue
    task_num = len(tasks)
    cmd_num = sum(sum(v["code"] != 0 for v in stat.values()) for stat in stats.values())
    queue = asyncio.Queue(maxsize=task_num)
    for index in range(task_num):
        queue.put_nowait(index)
    print("Tasks: {}, commands to run: {}".format(task_num, cmd_num))

    # build workers that consuming tasks in task_
    workers = []
    loop = asyncio.get_event_loop()
    for resource in resources:
        workers.append(loop.create_task(build_worker(tasks, queue, stats, resource)))
    await queue.join()

    for worker in workers:
        worker.cancel()
    await asyncio.gather(*workers, return_exceptions=True)
    failed = []
    for name, stat in stats.items():
        for code in set(info["code"] for info in stat.values()):
            if code > 0:
                failed.append(name)
                break

    if failed:
        color_print("Failed tasks: %d/%d" % (len(failed), len(tasks)), RED)
        print("rm -rf", end="")
        for name in failed:
            print(' \\\n    {}'.format(name), end="")
        print()
    else:
        color_print("No task failed.", GREEN)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("-o", "--output", default="output", help="Output directory of all experiments.")
    parser.add_argument("-c", "--config", default="params.yaml",
                        help="Yaml configuration file for present experiment group.")
    parser.add_argument("-p", "--param_choices", default="",
                        help="Extra param choices specified in string.")
    parser.add_argument("-d", "--debug", default=False, action='store_true',
                        help="Debug mode. Only run the first task, log will be directed to stdout.")
    parser.add_argument("--command", default=None, type=str,
                        help="Choose which command to run. All commands are ran by default.")
    parser.add_argument("--sample", default=None, type=int,
                        help="Number of random samples from each param choice. All combinations are ran by default.")
    parser.add_argument("--no-param-dir", default=False, action="store_true",
                        help="Do not create separated output directory for each param choice.")
    parser.add_argument("--no-shrink-dir", default=False, action="store_true",
                        help="Do not eliminate directory of directory params.")
    parser.add_argument("-f", "--force", default=False, action="store_true",
                        help="Overwrite tasks already run.")

    args = parser.parse_args()
    resources, tasks, stats, orphans = build_tasks(args)
    color_print("Orphan params: {}".format(orphans), RED)
    os.makedirs(args.output, exist_ok=True)
    shutil.copyfile(args.config, os.path.join(args.output, args.config))
    run(run_all(tasks, stats, resources))
