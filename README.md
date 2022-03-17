## Introduction

A light-weight tool to currently run experiments with different command line params.

During a typical iteration in neural network development, we need to deal with a batch of experiments.  I have seen two typical strategies adopted by my peers:
1. Run them one after another by hand, and manually paste each result in a spreadsheet 
2. Use a for loop in a bash script

Such strategies quickly bring frustration irrelevant to the improvements and insights we aim for:
1. Efficiency. During early phase we experiment on small models and datasets. They are not resource hungry. Both strategy fail to fully utilize modern multi-gpu machines.
2. Cognitive load. There are lengthy pipelines and numerous parameters to tune: data, model architecture, hyperparams, training regimes and test regimes. These knots are typically scatter in code, data or command-line args, making the process error-prone and cognitively draining.
3. Accessibility. How to distinguish different runs in the file system while maintaining human readability? How to quickly discover insights from tens of hundreds of results? How to minimally tweak the existing code to achieve efficiency?
4. Robustness: What if your machine is temporally down? Should you rerun all the experiments? 

Over the years I have developed an effective strategy to cope with these problems which relies on this tool. In a nutshell:
1. Pull every modification into command line args. This interface is consistent to most code base. 
   1. For model modification, use if/else or switch/case
   2. For datasets, specify it with directory
   3. Others can be set as flag or params
2. Specify the default params in a command template. Pull the params your care as variables and list the values you are interested in a configuration file. Specify the default values of these params.
3. Use a pool of workers to concurrently run the tasks. Dump all the relevant raw data into a directory named by the (param, value) tuples -- making them human-readable. Track the training progress with tensorboard.
4. Apply the same processing code for each run to obtain results you need, and aggregate them for visualization: tensorboard hyperparams or simply a spreadsheet.

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

Edit the yaml file. Then

```bash
run
# or
run -o <output> -y <yaml>
```

Use `run -h` for available command lines args. See `params.yaml` for available configurations.


## A working example
Suppose we are interested in different normalization layers and developed a new one called "alternorm". It has a hyperparameter "momentum", similar to existing methods batchnorm. Our baseline uses powernorm. Each run involves training, checkpoint average and test with the averaged checkpoint. So we can specify the following yaml config:

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
  norm: layer
  moment: 0.1

resource: [ 0, 1, 2, 3 ]


---
norm: [ power, alter, batch ]
moment: [ 0.1, 0.05 ]
```
After syncing the modified code and the yaml file to the server, we simply hit `run`. As we specify 4 workers each with only one gpu, there are 4 tasks run concurrently:
```
$ run
Orphan params: set()
Tasks: 6, commands to run: 18
START   gpu: 0, train: 1/ 6, output/Norm_power-Moment_0.1
START   gpu: 1, train: 2/ 6, output/Norm_alter-Moment_0.1
START   gpu: 2, train: 3/ 6, output/Norm_batch-Moment_0.1
START   gpu: 3, train: 4/ 6, output/Norm_power-Moment_0.1
START   gpu: 2, avg  : 3/ 6, output/Norm_batch-Moment_0.1
FAIL    gpu: 2, avg  : 3/ 6, output/Norm_batch-Moment_0.1
START   gpu: 2, train: 5/ 6, output/Norm_alter-Moment_0.1
START   gpu: 1, avg  : 2/ 6, output/Norm_alter-Moment_0.1
START   gpu: 1, test : 2/ 6, output/Norm_alter-Moment_0.1
START   gpu: 1, train: 6/ 6, output/Norm_batch-Moment_0.1
START   gpu: 3, avg  : 4/ 6, output/Norm_power-Moment_0.1
FAIL    gpu: 3, avg  : 4/ 6, output/Norm_power-Moment_0.1
START   gpu: 2, avg  : 5/ 6, output/Norm_alter-Moment_0.1
START   gpu: 2, test : 5/ 6, output/Norm_alter-Moment_0.1
...
```

We use `tensorboard --host $(hostname -I | awk '{print $1}') --logdir output` to track the training progress.

After all experiments are finished, we can examine the logs for debugging:
```
$ ls output/Norm_power-Moment_0.1
checkpoint51.pt
checkpoint52.pt
averaged_model.pt
log.train.20220316.030151
log.avg.20220316.030151
log.test.20220316.030151
param
stat
```

and start a jupyter notebook to analyze useful metrics. We provide `Examiner` as a container to iteratively apply the metric parser to all experiments and aggregate the results. In this example we simply parse the test log for the test BLEU:
```python
from runner.examine import Examiner
from functools import partial

# define a metric parser for each directory (experiment)
def get_bleu(command, path, experiment, caches):
    examples = prepare_examples(command, path, experiment)
    if examples is None:
        return
    try:
        preds = [e["D"] for e in examples]
        refs = [e["T"] if "T" in e else " ".join(e["C"]) for e in examples]
        bleu = compute_bleu(preds, refs)
        experiment.metric[command] = bleu
    except:
        pass

examiner = Examiner()  # container for parsed results
# register parser for each directory (experiment)
examiner.add(partial(get_bleu, "test"))
# run registered parser for directories matched by regex 
examiner.exam(output="output", regex=".*powernorm.*")
# print the tsv table that can be readily pasted to spreadsheet
examiner.table()
```


