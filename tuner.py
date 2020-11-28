# -*- coding: utf-8 -*-
import asyncio
import argparse
import yaml
import copy
import random
import itertools
import re
import os
import traceback
from datetime import datetime
from utils import param_dict2name, param_dict2command_args


def sweep(param_choices, num_sample=None):
    # random combination of param choices
    for key, values in param_choices.items():
        assert isinstance(values, list), "{} should be a list, not {}".format(key, type(values))

    param_lists = [[(key, value) for value in values] for key, values in param_choices.items()]
    cand_params = [list(param) for param in itertools.product(*param_lists)]
    if num_sample is not None:
        random.shuffle(cand_params)
        params = cand_params[:num_sample]
        params.sort()
    else:
        params = cand_params
    params = [dict(param) for param in params]
    print("Choose %d out of %d possible choices." % (len(params), len(cand_params)))
    return params


def remap_param_dict(param_dict, remaps):
    if not remaps:
        return copy.deepcopy(param_dict)

    new_param_dict = {}
    for key, value in param_dict.items():
        if key in remaps:
            if isinstance(remaps[key], list):
                # param replacement
                for new_key in remaps[key]:
                    new_param_dict[new_key] = value
            if isinstance(remaps[key], dict):
                # param remap
                assert value in remaps[key], \
                    "value of '{}' should be in {}".format(key, tuple(remaps[key].keys()))
                new_param_dict.update(remaps[key][value])
        else:
            new_param_dict[key] = value
    return new_param_dict


def build_tasks(filename, output, command=None, debug=False, sample=None, no_param_dir=False):
    # parse yaml file
    with open(filename) as fin:
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

    base_commands = safe_load("commands", dict, required=True)
    assert base_commands, "No commands."
    if command:
        assert command in base_commands, \
            "command={} is not in valid commands {}".format(command, tuple(base_commands.keys()))
    resources = safe_load("resources", list, required=True)
    resources = [str(i) for i in resources]
    remaps = safe_load("remaps", dict)
    dirs = safe_load("dirs", dict)
    escapes = safe_load("escapes", list)
    replaces = safe_load("replaces", list)

    if replaces:
        for s in replaces:
            assert isinstance(s, str), "Replace placeholder should be {}, but get {}.".format(str, type(s))

    # avoid unspecified replacement in commands
    for key, value in base_commands.items():
        to_replaces = set(re.findall("(?<=\[\[).*?(?=\]\])", value))
        if replaces:
            to_replaces = to_replaces - set(replaces)
        to_replaces = list(to_replaces)
        assert not to_replaces, \
            "Replace placeholders '{}' in command '{}' not specified in 'replaces' list.".format(to_replaces, key)

    for key, value in base_commands.items():
        base_commands[key] = ' '.join(value.strip().split())

    if remaps:
        for key, value in remaps.items():
            assert isinstance(value, (list, dict)), \
                "Invalid yaml format: '{}' in 'remaps' should be a list or dict.".format(key)

    choices = docs[1:]
    assert len(choices) > 0, "Invalid yaml format: no param choices available."

    # avoid unspecified replacement values in param choices.
    if replaces:
        for s in replaces:
            for i, choice in enumerate(choices):
                assert s in choice, "Replacement '{}' not in {}th choice: {}".format(s, i, choice)
                assert choice[s], "Replacement '{}' in {}th choice is empty: {}".format(s, i, choice)

    # build tasks
    param_dicts = []
    for choice in choices:
        param_dicts.extend(sweep(choice, num_sample=sample))

    tasks = []
    for param_dict in param_dicts:
        name = param_dict2name(param_dict, str_maxlen=100)
        if no_param_dir:
            output_dir = output
        else:
            output_dir = os.path.join(output, name)
        os.makedirs(output_dir, exist_ok=True)
        param_dict = remap_param_dict(param_dict, remaps)
        # assign directories params to param_dict
        if dirs:
            for key, value in dirs.items():
                param_dict[key] = os.path.join(output_dir, value)
                os.makedirs(param_dict[key], exist_ok=True)
        if escapes:
            for key in escapes:
                if key in param_dict:
                    del param_dict[key]

        replace_pairs = []
        if replaces:
            for key in replaces:
                if key in param_dict:
                    pattern = re.compile("\[\[{}\]\]".format(key))
                    replace_pairs.append((pattern, str(param_dict[key])))
                    del param_dict[key]

        # build execution commands
        commands = {}
        for key, value in base_commands.items():
            log_filename = "{}.log.{}.{}".format(os.path.join(output_dir, key),
                                                 datetime.now().strftime("%Y-%m-%d.%H:%M:%S"),
                                                 name)
            if command is not None and command != key:
                continue
            # direct logs to shell when only one task is running
            if debug:
                suffix = "2>&1 | tee {}".format(log_filename)
            else:
                suffix = "&> {}".format(log_filename)
            commands[key] = " ".join([value, param_dict2command_args(param_dict, bool_as_flag=True), suffix])
            for pattern, target in replace_pairs:
                commands[key] = pattern.sub(target, commands[key])
        tasks.append((name, commands))
        if debug:
            print("Enter debug mode. Only the first task will be ran.")
            break
    return resources, tasks


async def build_worker(task_queue, succeeded_names, failed_names, resource):
    while True:
        index, (name, commands) = await task_queue.get()
        prefix = "CUDA_VISIBLE_DEVICES={}".format(resource)
        for key, command in commands.items():
            commands[key] = " ".join([prefix, command])
        try:
            for key, command in commands.items():
                # TODO automatically sleep when resource limit not met
                process = await asyncio.create_subprocess_shell(command)
                print("Start task: {}-{}, gpu: {}, pid: {}, param: {}".format(index, key, resource, process.pid, name))
                await process.wait()
                if process.returncode != 0:
                    raise Exception("Exited unexpectedly:\n{}".format(command))
            succeeded_names.append(name)
        except Exception as e:
            traceback.print_exc()
            print(e)
            print("Failed task: {}/{}: {}".format(index, task_queue.maxsize, name))
            failed_names.append(name)
        task_queue.task_done()


async def run_all(tasks, resources):
    # populate the task queue
    task_queue = asyncio.Queue(maxsize=len(tasks))
    for index, task in enumerate(tasks):
        task_queue.put_nowait((index, task))
    print("Total: %d" % len(tasks))

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


def tune():
    parser = argparse.ArgumentParser()
    parser.add_argument("-o", "--output", default="output", help="Output directory of all experiments.")
    parser.add_argument("-c", "--config", default="params.yaml",
                        help="Yaml configuration file for present experiment group.")
    parser.add_argument("-d", "--debug", default=False, action='store_true',
                        help="Debug mode. Only run the first task, log will be directed to stdout.")
    parser.add_argument("--command", default=None, type=str,
                        help="Choose which command to run. All commands are ran by default.")
    parser.add_argument("--sample", default=None, type=int,
                        help="Number of random samples from each param choice. All combinations are ran by default.")
    parser.add_argument("--no-param-dir", default=False, action="store_true",
                        help="Do not create separated output directory for each param choice.")

    args = parser.parse_args()

    resources, tasks = build_tasks(filename=args.config,
                                   output=args.output,
                                   command=args.command,
                                   debug=args.debug,
                                   sample=args.sample,
                                   no_param_dir=args.no_param_dir)
    loop = asyncio.get_event_loop()
    loop.run_until_complete(run_all(tasks, resources))
