## Introduction

This is a light-weight script to run multiple experiments in parallel. It maintains a task(packaged commands to execute)
queue and a pool of workers. Each worker is assigned with a number of gpus. Each worker pulls a task from the queue and
run it with assigned resources IN PARALLEL.

Each task is assigned with a short name corresponding to its parameter choice. The same name is used to specify the
output directory.

To specify a group of tasks to run, just define valid choices of each parameter in a yaml config file. Then the script
will sweep all possible combinations and append them to the task queue. For large parameter space, you can use random
samples from the sweep.

## Dependencies

```
python >= 3.6.X
pyyaml
```

## Install

```
git clone https://github.com/simtony/runner.git
cd runner && pip install .
```

## Usage

Edit the yaml file. Then

```bash
run
# or
run -o <output> -y <yaml>

```

### Resources

A minimal yaml config is

```yaml
template:
  run: python run.py {param}

resource: [ 0, 1 ]

---
param: [ 1, 2, 3, 4 ]
```

`resource` stands for gpu index, each corresponds to an instance of the task `python run.py {param}`. In this example,
there are two gpus available and each instance is assigned with a gpu.
`python run.py 1` and `python run.py 2` will start first, `python run.py 3` and `python run.py 4` will run afterwards.

Sometimes gpu utilization is low and multiple training instance fits in to a single gpu. In this case you can
specify `resource: [0, 1, 0, 1]` to maximize gpu utilization. In this case, all 4 instances will run at the same time.

Sometimes an instance of task consumes more than 1 gpu. In this case you can specify `resource: ["0,1", "2,3"]`.

### Outputs and logs

By default, logs will be redirected to `<output>/<name_of_param>/log.command.<datetime>`.

If your code writes files to the disk, it is recommended to specify the output directory
to `{_output}=<output>/<name_of_param>`, e.g., `--tensorboard_dir {_output}/tb`.

If `--no-param-dir` is specified, the directory `output/<name_of_param>/` will not be created and logs will be
redirected to `output/<name_of_param>/log.command.<datetime>.<name_of_param>`. `{_output}=<output>`. 

This is useful when
you want to process a large file in parallel. For example, suppose you have a file `text.txt` to be parsed
with `parse.py`, which is written in single gpu. You can first split `text.txt` into `text.txt.0, text.txt.1, ...`, then
specify `params.yaml` as

```yaml
template:
  run: python parse.py {file}

resource: [ 0, 1 ]

---
file: [ text.txt.0, text.txt.1, ... ]
```

then `run -o output -y params.yaml --no-param-dir` will process all files in parallel and write the results in `output`.

### Debugging and selective running

By default, all param choices will be run and logs will be redirected
to `<output>/<name_of_param>/log.command.<datetime>`. During experiment, you may want to see the console outputs without
the bothering of `tail -f log.command`. In this case you may want to use debug mode `run -d`, which only runs the first
param choice and prints console outputs.

Commonly after debugging and testing all your code, you may want to run different experiments on different machines.
Copy the code to each machine and then modify `params.yaml` is annoying and error prone, in this case you can
use `-t <title>` to run param choices with different titles. For example

```yaml
template:
  run: python parse.py {file}

resource: [ 0, 1 ]

---
_title: machine1
file: [ text.txt.0, text.txt.1 ]

---
_title: machine2
file: [ text.txt.3, text.txt.4 ]
```

then you can simply run `run -t machine1` on machine1 and `run -t machine2` on machine2.

If multiple templates are defined, by default all of them will be run. But you may want to specify which command to run,
for example, train once on training set but test on different test sets. You can use `-c <command>` to select which
command to run.

```yaml
template:
  train: python train.py {file}
  test: python test.py {file}

resource: [ 0, 1 ]

---
file: [ text.txt.0, text.txt.1 ]
```

to only run test, `run -c test`.

### Examining results and rerunning experiments.

Additional to log files, `param.json` and `stat.json` are also written to `{_output}`.
`param.json` records relevant params and commands of the experiment.

```json
{
  "_commands": {
    "base": "CUDA_VISIBLE_DEVICES=1 echo 1 --bracket 1 2021-07-13.02:40:07 Curl_1-Bracket_1 output/Curl_1-Bracket_1 > output/Curl_1-Bracket_1/log.base.2021-07-13.02:40:07 2>&1",
    "pack": "CUDA_VISIBLE_DEVICES=1 echo 1 --bracket 1 > output/Curl_1-Bracket_1/log.pack.2021-07-13.02:40:07 2>&1",
    "remap": "CUDA_VISIBLE_DEVICES=1 echo --alias_remap_new_bracket1 1 --alias_remap_new_bracket2 2 > output/Curl_1-Bracket_1/log.remap.2021-07-13.02:40:07 2>&1",
    "replace": "CUDA_VISIBLE_DEVICES=1 echo --alias_replaced1 1 --alias_replaced2 1 > output/Curl_1-Bracket_1/log.replace.2021-07-13.02:40:07 2>&1"
  },
  "_datetime": "2021-07-13.02:40:07",
  "_name": "Curl_1-Bracket_1",
  "_output": "output/Curl_1-Bracket_1",
  "alias_remap": "remap1",
  "alias_replace": 1,
  "bracket": 1,
  "curl": 1,
  "remap": "remap1",
  "remap_bracket": 0,
  "remap_curl": 0,
  "replace": 1
}
```

`stat.json` records the running status of each command:
`0` for success and `1` for failure. Success commands will be skipped by default. To force rerun, specify `-f`.

```json
{
  "base": {
    "code": 0
  },
  "pack": {
    "code": 0
  },
  "remap": {
    "code": 0
  },
  "replace": {
    "code": 0
  }
}
```

### Parameter aliases, parameter packages and default parameters

TODO

