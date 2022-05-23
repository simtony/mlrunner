# Quick Start

Starting a large batch of experiments can be taxing. It is also difficult to minimize idle GPU time using manual
experiment scheduling. This is a light-weight tool to currently run experiments with different command line params,
solving all the above problems.

## Install

```
pip install mlrunner
```

dependencies:

```
python >= 3.7
pyyaml
```

## Usage

Edit `params.yaml` and then run `run` in command line.

Use `run -h` for documentation of command-line args. See comments in `params.yaml` for documentation of configurations available and parameter mapping rules.

## Under the Hood

The tool edits each command template with the following steps:
1. Substitute the param placeholders in the command templates of the first doc with sweep of params specified in later docs
2. Append shell environment variable `CUDA_VISIBLE_DEVICES={resource}` as the prefix
3. Append shell redirect `> output_dir/log.{command}.{time} 2>&1` as the suffix


## Example

Suppose we are interested in different normalization layers and developed a new one called "newnorm". It has a
hyperparameter "moment", similar to existing batchnorm. We also want to see how early stop affects our model, which is
specified by a boolean flag `--early-stop`. Each run involves training, checkpoint average and test with the averaged
checkpoint. So we can specify the following yaml config:

```yaml
---
template:
  train: >
    python train.py data-bin/{data} --seed 1
      --save-dir {_output}
      --tensorboard-logdir {_output}
      --max-epochs 80
      --normalization {norm}
      [moment] [early-stop]

  avg: >
    python scripts/average_checkpoints.py --inputs {_output}
      --num-epoch-checkpoints 5 --output {_output}/averaged_model.pt

  test: >
    python generate.py data-bin/{data}
        --max-tokens 4096 --beam 5 --lenpen 1.0 --remove-bpe
        --path {_output}/averaged_model.pt --gen-subset test

default:
  data: iwslt14
  norm: batch
  moment: 0.1
  early-stop: False

resource: [ 0, 1, 2, 3 ]


---
norm: [ new, batch ]
moment: [ 0.1, 0.05 ]

---
norm: [ batch ]
early-stop: [ True, False ]

```
The first doc (seperated by `---`) specifies command template (`template`), default value for each param (`default`), resource (gpu index) for each worker (`resource`) and other stuffs. Parameters we want to tune are specified in either square brackets or curly brackets in the template. In the second doc we specify the first experiment about hyperparams for newnorm and batchnorm. In the third doc is another experiment for the effect of early stopping. 

After syncing the code and the yaml file to the server, we simply hit `run`. As we specify 4 workers each with only one
gpu, there are 4 tasks running concurrently:

```
$ run
Orphan params: set()
Tasks: 6, commands to run: 18
START   gpu: 0, train: 1/ 4, output/Norm_new-Moment_0.1
START   gpu: 1, train: 2/ 4, output/Norm_new-Moment_0.05
START   gpu: 2, train: 3/ 4, output/Norm_batch-Moment_0.1
START   gpu: 3, train: 4/ 4, output/Norm_batch-Moment_0.05
START   gpu: 0, avg  : 1/ 4, output/Norm_new-Moment_0.1
FAIL    gpu: 0, avg  : 1/ 4, output/Norm_new-Moment_0.1
...
```

We can use `tensorboard --host $(hostname -I | awk '{print $1}') --logdir output` to track the training progress.

After all experiments are finished, we can examine the logs for debugging:

```
$ ls output/Norm_batch-Moment_0.1
checkpoint51.pt
checkpoint52.pt
averaged_model.pt
log.train.20220316.030151
log.avg.20220316.030151
log.test.20220316.030151
param
stat
```

and start a jupyter notebook to analyze interesting metrics. We provide `Examiner` as a container to iteratively apply
the metric parser to all experiments and aggregate the results. See the code for more details.

In this example we simply parse the test log for the test BLEU:

```python
from runner.examine import Examiner, latest_log


# define a metric parser for each directory (experiment)
def add_bleu(output_dir, experiment, caches):
    # Each parser follows the same signature
    # It can read/write to a global cache dict `caches`, 
    # and read/write each experiment: 
    # collections.namedtuple("Experiment", ["cache", "metric", "param"])
    latest_test_log = latest_log("test", output_dir)
    bleu = parse_bleu(latest_test_log)  # a user-defined log parser
    experiment.metric["test_bleu"] = bleu


examiner = Examiner()  # container for parsed results
# register parser for each directory (experiment)
examiner.add(add_bleu)
# run all parsers for directories matched by regex 
examiner.exam(output="output", regex=".*powernorm.*")
# print the tsv table with all (different) params and metrics of each experiment
examiner.table()
```

# Few Words on DL Iteration

During neural network development, we need to deal with a batch of experiments. Two naive strategies are commonly
adopted:

1. Run them one after another by hand, and manually paste each result in a spreadsheet
2. Use a for loop in a bash script

Such strategies quickly bring frustration irrelevant to the improvements and insights we aim for:

1. Efficiency. During early phase we experiment on small models and datasets. They are not resource hungry. Both
   strategy fail to fully utilize modern multi-gpu machines.
2. Cognitive load. There are lengthy pipelines and numerous parameters to tune: data, model architecture, hyperparams,
   training regimes and test regimes. These knots are typically scatter in code, data or command-line args, making the
   process error-prone and cognitively draining.
3. Accessibility. How to distinguish different runs in the file system while maintaining human readability? How to
   quickly discover insights from tens of hundreds of results? How to minimally tweak the existing code to achieve
   efficiency?
4. Robustness: What if your machine is temporally down? Should you rerun all the experiments?

Over the years I have developed an effective workflow to cope with these problems. This tool tightly integrates into the
workflow. In a nutshell:

1. Make every modification (architecture, hyperparameters, training regime, etc.) adjustable by command line args. This
   interface is consistent to most code base.
    1. For model modification, use if/else or switch/case
    2. For datasets, specify the directory
2. Specify the default params in a command template. Make interesting params variables and list their available values
   in a configuration file. Specify default values of these params.
3. Use a pool of workers to concurrently run tasks specified in the config file. Dump all the relevant raw data into a
   directory named by the (param, value) tuples -- making them human-readable yet distinct for each experiment. Track
   the training progress with tensorboard.
4. Apply the same processing code for each run to parse results you need, and aggregate them for visualization: use
   tensorboard hyperparams, jupyter notebook or simply a spreadsheet.

