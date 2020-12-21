# -*- coding: utf-8 -*-
import asyncio
import argparse
import yaml
import random
import itertools
import re
import os
import traceback
import json
import shutil
from datetime import datetime
from tuner.utils import param_dict2name, param_dict2command_args


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
    with open(args.config) as fin:
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
    name2uniq_commands = {name: set() for name in name2template.keys()}
    tasks = []
    for param_dict in itertools.chain.from_iterable(sweep(choice, num_sample=args.sample) for choice in choices):
        # prepare param_dict
        name = param_dict2name(param_dict, str_maxlen=100, no_shrink_dir=args.no_shrink_dir)
        param_dict["_name"] = name
        if args.no_param_dir:
            param_dict["_output"] = args.output
        else:
            param_dict["_output"] = os.path.join(args.output, name)
        param_dict["_datetime"] = datetime_str
        for key, value in defaults.items():
            if key not in param_dict:
                param_dict[key] = value

        # prepare command
        name2command = {}
        duplicate = True
        for name, command_template in name2template.items():
            if args.command is not None and args.command != name:
                continue
            empty_params = []
            command = command_template
            for curly_param in re.findall(r"{.+?}", command):
                param = curly_param.strip("{}")
                if param in param_dict:
                    s = str(param_dict[param])
                    command = command.replace(curly_param, s)
                else:
                    empty_params.append(curly_param)
            for square_param in re.findall(r"\[.+?\]", command):
                param = square_param.strip("[]")
                if param in param_dict:
                    s = param_dict2command_args(safe_alias(param, param_dict[param]), bool_as_flag=True)
                    command = command.replace(square_param, s)
                else:
                    empty_params.append(square_param)

            assert not empty_params, "params {} are not specified in 'default' or 'param_choice'".format(empty_params)
            command = " ".join(command.split())
            # check for duplication
            if command not in name2uniq_commands[name]:
                duplicate = False
                name2uniq_commands[name].add(command)
            name2command[name] = command
        if duplicate:
            continue

        # append suffix to commands
        for name, command in name2command.items():
            log_file = "log.{}.{}.{}".format(name, param_dict["_datetime"], param_dict["_name"])
            log_path = os.path.join(param_dict["_output"], log_file)
            if args.debug:
                suffix = "2>&1 | tee {}".format(log_path)
            else:
                suffix = "&> {}".format(log_path)
            name2command[name] = command + " " + suffix
        tasks.append((param_dict, name2command))

    if args.debug:
        tasks = tasks[:1]
    return resources, tasks


async def build_worker(task_queue, succeeded_names, failed_names, resource):
    while True:
        index, (param_dict, name2command) = await task_queue.get()
        prefix = "CUDA_VISIBLE_DEVICES={}".format(resource)
        os.makedirs(param_dict["_output"], exist_ok=True)
        for key, command in name2command.items():
            name2command[key] = " ".join([prefix, command])
        param_dict["_commands"] = name2command
        with open(os.path.join(param_dict["_output"], "param.json"), "w") as fout:
            json.dump(param_dict, fout, sort_keys=True, indent=4)
        try:
            for key, command in name2command.items():
                process = await asyncio.create_subprocess_shell(command)
                print("Start task: {}-{}, gpu: {}, pid: {}, param: {}".format(index, key, resource, process.pid,
                                                                              param_dict["_name"]))
                await process.wait()
                if process.returncode != 0:
                    raise Exception("Exited unexpectedly:\n{}".format(command))
            succeeded_names.append(param_dict["_name"])
        except Exception as e:
            traceback.print_exc()
            print(e)
            print("Failed task: {}/{}: {}".format(index, task_queue.maxsize, param_dict["_name"]))
            failed_names.append(param_dict["_name"])
        task_queue.task_done()


async def run_all(tasks, resources):
    # populate the task queue
    task_queue = asyncio.Queue(maxsize=len(tasks))
    for index, task in enumerate(tasks):
        task_queue.put_nowait((index, task))
    print("Total unique tasks: %d" % len(tasks))
    # build workers that consuming tasks in task_queue asynchronously
    succeeded_names = []
    failed_names = []
    workers = []
    loop = asyncio.get_event_loop()
    for resource in resources:
        workers.append(loop.create_task(build_worker(task_queue, succeeded_names, failed_names, resource)))
    await task_queue.join()

    for worker in workers:
        worker.cancel()
    await asyncio.gather(*workers, return_exceptions=True)

    print("Failed tasks: %d/%d" % (len(failed_names), len(tasks)))
    if failed_names:
        print("    rm -rf \\")
        for name in failed_names:
            print('    %s \\' % name)


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

    args = parser.parse_args()
    resources, tasks = build_tasks(args)
    os.makedirs(args.output, exist_ok=True)
    shutil.copyfile(args.config, os.path.join(args.output, args.config))
    loop = asyncio.get_event_loop()
    loop.run_until_complete(run_all(tasks, resources))
