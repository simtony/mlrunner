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
from runner.utils import param_dict2name, param_dict2command_args, json_load, json_dump, color_print, RED, GREEN


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
    with open(args.yaml, "r") as fin:
        docs = list(yaml.load_all(fin, Loader=yaml.FullLoader))
    assert len(docs) > 1, "Empty yaml file."
    config = docs[0]  # first doc for meta data

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
    packs = safe_load("pack", dict)
    if aliases:
        for key, value in aliases.items():
            assert isinstance(value, (list, dict)), \
                "Invalid yaml format: '{}' in 'alias' should be a list or dict.".format(key)
    if packs:
        for key, value in aliases.items():
            assert isinstance(value, (list, dict)), \
                "Invalid yaml format: '{}' in 'pack' should be a list or dict.".format(key)

    choices = docs[1:]  # first doc for meta data
    assert len(choices) > 0, "Invalid yaml format: no param choices available."
    if args.title is not None:
        is_title_unset = True
        is_title_not_exist = True
        temp_choices = []
        for choice in choices:
            if "_title" in choice:
                is_title_unset = False
                if choice["_title"] == args.title:
                    is_title_not_exist = False
                    temp_choices.append(choice)
        choices = temp_choices
        assert not is_title_unset, "'_title' not in any param choices"
        assert not is_title_not_exist, "No param choices having '_title'={}".format(args.title)
        color_print("Run param choices with title '{}'".format(args.title), GREEN)
        color_print(yaml.dump_all(choices, default_flow_style=True, explicit_start=True), GREEN)

    for choice in choices:
        if "_title" in choice:
            del choice["_title"]
    # build task commands and de-duplication
    datetime_str = datetime.now().strftime("%Y-%m-%d.%H:%M:%S")
    orphan_param_keys = set()  # track params not consumed by any command.
    uniq_param_dicts = []  # avoid duplication
    tasks = []
    stats = dict()

    def get_pack_or_alias(key, value, packs_or_aliases):
        assert key in packs_or_aliases
        if isinstance(packs_or_aliases[key], list):
            # param replacement
            return {new_key: value for new_key in packs_or_aliases[key]}
        if isinstance(packs_or_aliases[key], dict):
            # param remap
            assert value in packs_or_aliases[key], \
                "value of '{}' should be in {}".format(key, tuple(packs_or_aliases[key].keys()))
            return packs_or_aliases[key][value]

    for param_dict in itertools.chain.from_iterable(sweep(choice, num_sample=args.sample) for choice in choices):
        # get name before messing up with param_dict
        name = param_dict2name(param_dict, str_maxlen=100, no_shrink_dir=args.no_shrink_dir)

        # update with packed params
        pack_update_dict = dict()
        pack_param = set()
        for param, value in param_dict.items():
            if param in packs:
                pack_param.add(param)
                pack_update_dict.update(get_pack_or_alias(param, value, packs))
        for param in pack_param:
            del param_dict[param]
        param_dict.update(pack_update_dict)

        # update missing with default
        for param, value in defaults.items():
            if param not in param_dict:
                param_dict[param] = value

        # deduplication
        if param_dict in uniq_param_dicts:
            continue
        else:
            uniq_param_dicts.append(copy.deepcopy(param_dict))

        param_keys = set(param_dict.keys())
        # filling builtin params
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
            # fill in curly params
            for curly_param in re.findall(r"{[\w-]+?}", command):
                param = curly_param.strip("{}")
                assert param not in packs, "Packed param '{}' should not be specified in command.".format(param)
                if param in param_keys:
                    param_keys.remove(param)
                if param in param_dict:
                    s = str(param_dict[param])
                    command = command.replace(curly_param, s)
                else:
                    empty_params.append(curly_param)

            # fill in square params and perform param remap
            for square_param in re.findall(r"\[[\w-]+?\]", command):
                param = square_param.strip("[]")
                assert param not in packs, "Packed param '{}' should not be specified in command.".format(param)
                if param in param_keys:
                    param_keys.remove(param)
                if param in param_dict:
                    if param in aliases:
                        s = param_dict2command_args(get_pack_or_alias(param, param_dict[param], aliases),
                                                    bool_as_flag=True)
                    else:
                        s = param_dict2command_args({param: param_dict[param]}, bool_as_flag=True)
                    command = command.replace(square_param, s)
                else:
                    empty_params.append(square_param)

            assert not empty_params, "params {} are not specified in 'default' or 'param_choice'".format(empty_params)
            command = " ".join(command.split())  # clear messed spaces

            # extra params for logging
            if args.no_param_dir:
                log_file = "log.{}.{}.{}".format(name, param_dict["_datetime"], param_dict["_name"])
            else:
                log_file = "log.{}.{}".format(name, param_dict["_datetime"])
            log_path = os.path.join(param_dict["_output"], log_file)

            if args.debug:
                suffix = "2>&1 | tee {}".format(log_path) + "; exit ${PIPESTATUS[0]}"
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
            info = "{:5}:{:2d}/{:2d}, {}".format(key, index + 1, queue.maxsize, param_dict["_output"])
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
        for name in failed:
            color_print('    {}'.format(name), RED)
    else:
        color_print("No task failed.", GREEN)


def main():
    parser = argparse.ArgumentParser(formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    parser.add_argument("-o", "--output", default="output", help="output directory of all experiments")
    parser.add_argument("-y", "--yaml", default="params.yaml",
                        help="yaml configuration file")
    parser.add_argument("-t", "--title", default=None, help="choose param choices with specified title to sweep")
    parser.add_argument("-d", "--debug", default=False, action='store_true',
                        help="debug mode: only run the first task, log will be directed to stdout.")
    parser.add_argument("-c", "--command", default=None, type=str,
                        help="choose which command to run, by default run all commands")
    parser.add_argument("-f", "--force", default=False, action="store_true",
                        help="whether to overwrite tasks successfully ran")

    parser.add_argument("--sample", default=None, type=int,
                        help="number of random samples from each param choice, by default all params choices are ran")
    parser.add_argument("--no-param-dir", default=False, action="store_true",
                        help="do not create separated output directory for each param choice")
    parser.add_argument("--no-shrink-dir", default=False, action="store_true",
                        help="do not eliminate directory of directory params")

    args = parser.parse_args()
    resources, tasks, stats, orphans = build_tasks(args)
    color_print("Orphan params: {}".format(orphans), RED)
    os.makedirs(args.output, exist_ok=True)
    shutil.copyfile(args.yaml,
                    os.path.join(args.output, args.yaml if args.title is None else args.yaml + "." + args.title))
    run(run_all(tasks, stats, resources))
