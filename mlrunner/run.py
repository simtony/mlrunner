# -*- coding: utf-8 -*-
import asyncio
import argparse
import random
import itertools
import shlex
import re
import types
import copy
import sys
import os
import shutil
from datetime import datetime
from mlrunner.utils.misc import spec2name, map_placeholder, map_replacement, shell_arg, \
    yaml_load, yaml_dump, color_print, edit_yaml
from mlrunner.utils.config import load_yaml, InvalidYAMLException

TIME = datetime.now().strftime("%Y%m%d.%H%M%S")


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
        if not isinstance(values, list):
            raise InvalidYAMLException("{} should be a list, not {}".format(key, type(values)))

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


# param_dict updates
def map_alias(param_dict, aliases):
    def resolve_alias(key, value):
        if key not in aliases:
            raise InvalidYAMLException("{} not in 'alias'.")
        # aliases[key] already asserted as a dict
        if value not in aliases[key]:
            raise InvalidYAMLException("value of '{}' should be one of {}".format(key, tuple(aliases[key].keys())))
        return aliases[key][value]

    update_dict = dict()
    alias_param = set()
    for param, value in param_dict.items():
        if param in aliases:
            alias_param.add(param)
            update_dict.update(resolve_alias(param, value))
    for param in alias_param:
        del param_dict[param]
    param_dict.update(update_dict)


def add_default(param_dict, defaults):
    for param, value in defaults.items():
        if param not in param_dict:
            param_dict[param] = value


def parse_choice(args, choice, aliases, defaults):
    # update commands
    if "_cmd" in choice:
        commands = choice["_cmd"]
        del choice["_cmd"]
    else:
        commands = None
    entries = []
    for spec in sweep(choice, num_sample=args.sample):
        name = spec2name(spec, str_maxlen=100)
        meta = {
            "_name":   name,
            "_time":   TIME,
            "_output": args.output if args.no_subdir else os.path.join(args.output, name)
        }
        map_alias(spec, aliases)
        add_default(spec, defaults)
        entries.append((spec, meta))
    return commands, entries


def build_tasks(args, templates, aliases, defaults, choices):
    def uniq_entries(entries):
        for spec, meta in entries:
            if spec in uniq_entries.uniq_spec:
                # allow the same task with different command.
                # repeated commands will be skipped later by checking stat
                if meta["_output"] not in uniq_entries.uniq_output:
                    continue
            else:
                uniq_entries.uniq_spec.append(copy.deepcopy(spec))
                uniq_entries.uniq_output.append(meta["_output"])
            yield spec, meta

    uniq_entries.uniq_spec = []
    uniq_entries.uniq_output = []

    tasks = []
    orphans = set()  # track params not consumed by any command
    for choice in choices:
        commands, entries = parse_choice(args, choice, aliases, defaults)
        if args.command:
            # command line option will override those in the yaml config
            commands = args.command
        entries = uniq_entries(entries)
        for spec, meta in entries:
            unused_params = set(spec.keys())  # avoid accidentally missing the param in the template
            spec.update(meta)
            scripts = {}
            for command, template in templates.items():
                if commands and command not in commands:
                    continue
                template = re.sub(r"\s*\n\s*", " ", template)  # clean up line breaks
                # fill placeholder with params
                empties = set()
                placeholders = re.findall(r"{[\w\-\_]+?}", template)  # {param} -> value
                replacements = re.findall(r"\[[\w\-\_]+?\]", template)  # [param] -> --param value
                intersect = set(p.strip("{}") for p in placeholders) & set(r.strip("[]") for r in replacements)
                if intersect:
                    raise InvalidYAMLException("duplicate params in placeholder and replacement: {}".format(intersect))

                for placeholder in placeholders:
                    param = placeholder.strip("{}")
                    if param in aliases:
                        raise InvalidYAMLException(
                                "alias param '{}' should not be specified in template.".format(param))
                    if param in unused_params:
                        unused_params.remove(param)
                    if param in spec:
                        template = template.replace(placeholder, map_placeholder(spec, param))
                    else:
                        empties.add(placeholder)

                for replacement in replacements:
                    param = replacement.strip("[]")
                    if param in aliases:
                        raise InvalidYAMLException(
                                "alias param '{}' should not be specified in template.".format(param))
                    if param in unused_params:
                        unused_params.remove(param)
                    if param in spec:
                        template = template.replace(replacement, map_replacement(spec, param))
                    else:
                        empties.add(replacement)
                if empties:
                    raise InvalidYAMLException("params {} are not specified in 'default' or 'choice'".format(empties))

                # prepare suffix for logging
                if args.no_subdir:
                    log = "log.{}.{}.{}".format(command, spec["_time"], spec["_name"])
                else:
                    log = "log.{}.{}".format(command, spec["_time"])
                log = shell_arg(os.path.join(spec["_output"], log))

                if args.debug:
                    # log_path may contain tokens that should be escaped in shell.
                    # os.makedirs implicitly handle it, here we should handle it explicitly.
                    suffix = "2>&1 | tee {}".format(log) + "; exit ${PIPESTATUS[0]}"
                else:
                    suffix = "> {} 2>&1".format(log)
                scripts[command] = template + " " + suffix
            orphans.update(unused_params)
            tasks.append({"spec": spec, "scripts": scripts})
    color_print("Orphan params: {}".format(orphans), "red")
    if args.debug:
        tasks = tasks[:1]
        args.force = True
    return tasks


async def build_worker(tasks, queue, resource, skips, fails, force=False, dry_run=False):
    while True:
        index = await queue.get()
        spec, scripts = tasks[index]["spec"], tasks[index]["scripts"]
        prefix = "CUDA_VISIBLE_DEVICES={}".format(resource)
        for command, script in scripts.items():
            scripts[command] = " ".join([prefix, script])
        spec["_scripts"] = scripts

        os.makedirs(spec["_output"], exist_ok=True)
        # dump param
        with edit_yaml(spec["_output"], "param") as prev_spec:
            if not prev_spec:
                prev_spec.update(spec)
            else:
                for key, value in spec.items():
                    # don't overwrite old commands
                    if key == "_scripts":
                        prev_spec[key].update(spec[key])
                    else:
                        prev_spec[key] = spec[key]
        for command, script in scripts.items():
            info = "{:8}:{:2d}/{:2d}, {}".format(command, index + 1, queue.maxsize, shell_arg(spec["_output"]))
            try:
                with edit_yaml(spec["_output"], "stat") as stat:
                    if command in stat and stat[command] in ["finished", "running"] and not force:
                        color_print("SKIP " + info, "green")
                        skips.append(spec["_output"])
                        continue
                    else:
                        stat[command] = "running"
                info = "gpu: {}, ".format(resource) + info
                print("START   " + info)
                if dry_run:
                    print(script)
                    await asyncio.sleep(0.05)
                else:
                    process = await asyncio.create_subprocess_shell(script, executable='/bin/bash')
                    await process.wait()
                    code = process.returncode
                    stat_path = os.path.join(spec["_output"], "stat")
                    with edit_yaml(spec["_output"], "stat") as stat:
                        if code != 0:
                            stat[command] = "failed"
                            color_print("FAIL    " + info, "red")
                            fails.append(spec["_output"])
                            break
                        else:
                            stat[command] = "finished"
            except Exception as exception:
                with edit_yaml(spec["_output"], "stat") as stat:
                    stat[command] = "failed"
                    fails.append(spec["_output"])
                raise exception
            except asyncio.CancelledError as error:
                with edit_yaml(spec["_output"], "stat") as stat:
                    stat[command] = "failed"
                    fails.append(spec["_output"])
                raise error
        queue.task_done()


async def run_all(args, tasks, resources):
    # populate the task queue
    task_num = len(tasks)
    cmd_num = sum(len(task["scripts"]) for task in tasks)
    print("Tasks: {}, Commands: {}".format(task_num, cmd_num))
    queue = asyncio.Queue(maxsize=task_num)
    for index in range(task_num):
        queue.put_nowait(index)
    # build workers that consuming tasks in task_
    skips = []
    fails = []
    workers = []
    loop = asyncio.get_event_loop()
    for resource in resources:
        workers.append(loop.create_task(build_worker(tasks, queue, resource, skips, fails, force=args.force,
                                                     dry_run=args.dry_run)))
    await queue.join()

    for worker in workers:
        worker.cancel()
    await asyncio.gather(*workers, return_exceptions=True)
    if skips:
        color_print("Skipped tasks: {}/{}".format(len(skips), len(tasks)), "green")
        for name in skips:
            color_print('    {}'.format(name), "green")

    if fails:
        color_print("Failed tasks: {}/{}".format(len(skips), len(tasks)), "red")
        for name in fails:
            color_print('    {}'.format(name), "red")
    else:
        color_print("No task failed.", "green")


def main():
    parser = argparse.ArgumentParser(formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    parser.add_argument("-o", "--output", default="output", help="output directory of all experiments")
    parser.add_argument("-y", "--yaml", default="params.yaml",
                        help="yaml configuration file")
    parser.add_argument("-t", "--title", default=None, help="choose param choices with specified title to sweep")
    parser.add_argument("-d", "--debug", default=False, action='store_true',
                        help="debug mode: only run the first task, log will be directed to stdout.")
    parser.add_argument("--dry-run", default=False, action='store_true',
                        help="dry run mode: only print the scripts to be run.")
    parser.add_argument("-c", "--command", default=None, type=str, nargs="+",
                        help="choose which command to run, by default run all commands")
    parser.add_argument("-f", "--force", default=False, action="store_true",
                        help="whether to overwrite tasks successfully ran")
    parser.add_argument("-r", "--resource", default="", nargs="+",
                        help="override resources in params.yaml with a space separate list, "
                             "for example `-r 1,2 3,4` gives ['1,2', '3,4']")
    parser.add_argument("--sample", default=None, type=int,
                        help="number of random samples from each param choice, by default all params choices are ran")
    parser.add_argument("--no-subdir", default=False, action="store_true",
                        help="do not create separated directory for each param choice")

    args = parser.parse_args()
    resources, templates, aliases, defaults, choices = load_yaml(args)
    tasks = build_tasks(args, templates, aliases, defaults, choices)

    os.makedirs(args.output, exist_ok=True)
    yaml_bak = os.path.basename(args.yaml)
    yaml_bak_path = os.path.join(args.output, yaml_bak if args.title is None else yaml_bak + "." + args.title)
    shutil.copyfile(args.yaml, yaml_bak_path)
    run(run_all(args, tasks, resources))
