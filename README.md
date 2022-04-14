# Quick Start

Starting a large batch of experiments can be taxing. It is also difficult to minimize idle GPU time using manual experiment scheduling. This is a light-weight tool to currently run experiments with different command line params, solving all the above problems.

## Install

```
pip install git+https://github.com/simtony/runner.git
```
dependencies:
```
python >= 3.6.X
pyyaml
```

## Usage

Edit `params.yaml` and then run `run` in command line. 

Use `run -h` for documentation of command-line args. See `params.yaml` for configurations available.

## Example
Suppose we are interested in different normalization layers and developed a new one called "newnorm". It has a hyperparameter "momentum", similar to existing batchnorm. Each run involves training, checkpoint average and test with the averaged checkpoint. So we can specify the following yaml config:

```yaml
---
template:
  train: >
    python train.py data-bin/{data}
      --seed 1
      --criterion label_smoothed_cross_entropy
      --arch transformer_iwslt_de_en_v2 --share-all-embeddings
      --optimizer adam --adam-betas '(0.9,0.98)' --clip-norm 0.0
      --dropout 0.3 --attention-dropout 0.1 --relu-dropout 0.1
      --lr-scheduler inverse_sqrt --warmup-init-lr 1e-07 --warmup-updates 8000
      --lr 0.0015 --min-lr 1e-09
      --label-smoothing 0.1 --weight-decay 0.0001
      --max-tokens 4096 
      --save-dir {_output}
      --tensorboard-logdir {_output}
      --no-save-optimizer-state
      --update-freq 1 --log-format simple --log-interval 50
      --ddp-backend no_c10d
      --keep-last-epochs 5 --early-stop 5
      --norm-momentum {moment}
      --normalization {norm}

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

resource: [ 0, 1, 2, 3 ]


---
norm: [ new, batch ]
moment: [ 0.1, 0.05 ]
```
After syncing the code and the yaml file to the server, we simply hit `run`. As we specify 4 workers each with only one gpu, there are 4 tasks running concurrently:
```
$ run
Orphan params: set()
Tasks: 4, commands to run: 12
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

and start a jupyter notebook to analyze interesting metrics. We provide `Examiner` as a container to iteratively apply the metric parser to all experiments and aggregate the results. See the code for more details.

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
    bleu = parse_bleu(latest_test_log) #  a user-defined log parser
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

During neural network development, we need to deal with a batch of experiments. Two naive strategies are commonly adopted:
1. Run them one after another by hand, and manually paste each result in a spreadsheet 
2. Use a for loop in a bash script

Such strategies quickly bring frustration irrelevant to the improvements and insights we aim for:
1. Efficiency. During early phase we experiment on small models and datasets. They are not resource hungry. Both strategy fail to fully utilize modern multi-gpu machines.
2. Cognitive load. There are lengthy pipelines and numerous parameters to tune: data, model architecture, hyperparams, training regimes and test regimes. These knots are typically scatter in code, data or command-line args, making the process error-prone and cognitively draining.
3. Accessibility. How to distinguish different runs in the file system while maintaining human readability? How to quickly discover insights from tens of hundreds of results? How to minimally tweak the existing code to achieve efficiency?
4. Robustness: What if your machine is temporally down? Should you rerun all the experiments? 

Over the years I have developed an effective workflow to cope with these problems. This tool tightly integrates into the workflow. In a nutshell:
1. Make every modification (architecture, hyperparameters, training regime, etc.) adjustable by command line args. This interface is consistent to most code base. 
   1. For model modification, use if/else or switch/case
   2. For datasets, specify the directory
2. Specify the default params in a command template. Make interesting params variables and list their available values in a configuration file. Specify default values of these params.
3. Use a pool of workers to concurrently run tasks specified in the config file. Dump all the relevant raw data into a directory named by the (param, value) tuples -- making them human-readable yet distinct for each experiment. Track the training progress with tensorboard.
4. Apply the same processing code for each run to parse results you need, and aggregate them for visualization: use tensorboard hyperparams, jupyter notebook or simply a spreadsheet.

