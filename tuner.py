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


# GPU sorting
def query_gpus():
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


def sort_single_gpus(gpus, min_mem=None):
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


def param_dict2command_args(param, bool_as_flag=True):
    args = []
    flags = []
    for key, value in param.items():
        if bool_as_flag and isinstance(value, bool):
            if value:
                flags.append('--{}'.format(key))
        else:
            args.append('--{} {}'.format(key, value))
    return ' ' + ' '.join(flags + args)


def snake2camel(snake_str, shrink_keep=0):
    """
    "a_snake_case_string" to "ASnakeCaseString"
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


def entry2str(name, value, str_maxlen):
    name = snake2camel(name, shrink_keep=2)
    if isinstance(value, str):
        if len(value) > str_maxlen:
            value = value[-str_maxlen:]
        # avoid directory split when used as directory name
        value = re.sub("^[/.]*", "", value)
        value = re.sub("/", "_", value)
    elif isinstance(value, bool):
        if value:
            value = "T"
        else:
            value = "F"
    elif isinstance(value, (float, int)):
        value = "%g" % value
    else:
        value = str(value)
    return name + '=' + value


def param_dict2name(param, str_maxlen):
    keys = list(param.keys())
    keys.sort()
    strs = [entry2str(key, value, str_maxlen) for key, value in param.items()]
    name = ','.join(strs)
    return name


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


def maybe_mkdir(dirname):
    if not os.path.exists(dirname):
        os.makedirs(dirname, exist_ok=True)
    return dirname


def parse_yaml(filename):
    with open(filename) as fin:
        docs = list(yaml.load_all(fin, Loader=yaml.FullLoader))
    assert len(docs) > 1
    config = docs[0]
    for field in ["commands", "remaps", "dirs"]:
        assert field in config, "Invalid yaml format: '{}' should be in the first doc.".format(field)

    commands = config["commands"]
    assert isinstance(commands, dict), "Invalid yaml format: 'commands' should be a dict."
    for key, value in commands.items():
        commands[key] = value.strip()

    remaps = config["remaps"]
    if remaps:
        for key, value in remaps.items():
            assert isinstance(value, (list, dict)), \
                "Invalid yaml format: '{}' in 'remaps' should be a list or dict.".format(field)

    dirs = config["dirs"]
    if dirs:
        assert isinstance(dirs, dict), "Invalid yaml format: 'dirs' should be a dict."

    resources = config["resources"]
    assert isinstance(resources, list), \
        "Invalid yaml format: 'resources' should be a list of strings."

    choices = docs[1:]
    assert len(choices) > 0, "Invalid yaml format: no param choices available."
    return commands, remaps, dirs, resources, choices


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


def build_tasks(base_commands, remaps, dirs, choices, output, run=None, first=False, sample=None):
    param_dicts = []
    for choice in choices:
        param_dicts.extend(sweep(choice, num_sample=sample))

    tasks = []
    for param_dict in param_dicts:
        name = param_dict2name(param_dict, str_maxlen=100)
        base_dir = os.path.join(output, name)
        param_dict = remap_param_dict(param_dict, remaps)
        # assign directories params to param_dict
        if dirs:
            for key, value in dirs.items():
                param_dict[key] = maybe_mkdir(os.path.join(base_dir, value))

        # build execution commands
        commands = {}
        for key, value in base_commands.items():
            if run is not None and run != key:
                continue
            # direct logs to shell when only one task is running
            suffix = "| tee {}.log".format(os.path.join(base_dir, key)) if first else "> {}.log".format(
                    os.path.join(base_dir, key))
            commands[key] = " ".join([value, param_dict2command_args(param_dict, bool_as_flag=True), suffix])
        assert commands, "run={} is not in valid commands {}".format(run, tuple(base_commands.keys()))
        tasks.append((name, commands))
        if first:
            break
    return tasks


async def build_worker(task_queue, succeeded_names, failed_names, resource):
    while True:
        index, (name, commands) = await task_queue.get()
        prefix = "CUDA_VISIBLE_DEVICES={}".format(resource)
        for key, command in commands.items():
            commands[key] = " ".join([prefix, command])
        try:

            for key, command in commands.items():
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
    parser.add_argument("-o", "--output", default="output", help="Root dir for output of experiments.")
    parser.add_argument("-c", "--config", default="params.yaml", help="Config file for present experiment group.")
    parser.add_argument("-f", "--first", default=False, action='store_true',
                        help="Used for debug, only run the first task, logging information will be redirected to stdout.")
    parser.add_argument("-r", "--run", default=None, type=str,
                        help="Choose which command to run. All commands are ran by default.")
    parser.add_argument("-s", "--sample", default=None, type=int,
                        help="Number of random samples from each parameter choice. All combinations are ran by default.")
    args = parser.parse_args()
    base_commands, remaps, dirs, resources, choices = parse_yaml(args.config)
    tasks = build_tasks(base_commands, remaps, dirs,
                        choices, args.output, run=args.run, first=args.first, sample=args.sample)

    if resources and len(resources[0].split(',')) > 1 and args.first:
        resources = sort_single_gpus(resources)
    loop = asyncio.get_event_loop()
    loop.run_until_complete(run_all(tasks, resources))
