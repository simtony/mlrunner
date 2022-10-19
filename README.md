![](logo.png)
Maintaining many machine learning experiments requires much manual effort. This lightweight tool helps you currently run a **LOT** of experiments with simple commands and configurations. You can easily aggregate custom metrics for each experiment with a single line of code.

## Install
```
$ pip install mlrunner
```
## Usage
Download and edit [params.yaml](https://raw.githubusercontent.com/simtony/mlrunner/main/params.yaml), then simply
```
$ run
```
When all experiments finish, start a jupyter notebook and analyze results using `examine.Examiner`.

See `examples` for typical use cases. 
See comments in `params.yaml` for available configurations. Use `run -h` for available command-line args.

## Example
Suppose we develop a new normalization layer "newnorm" and want to compare it to batchnorm. Both have a
hyperparameter `--moment`. We also want to see how early stop affects our model, which is
specified by a boolean flag `--early-stop`. Each run involves training, checkpoint average and test with the averaged checkpoint. Then `params.yaml` can be:

```yaml
---
# All commands for each experiment with params to be filled specified as `{param}` or `[param]`
# `{_output}` is a reserved param for the automatically generated output directory
template:
  train: >
    python train.py data-bin/{data} --save-dir {_output} --norm {norm} [moment] [early-stop]

  avg: >
    python checkpoint_avg.py --inputs {_output} --num 5 --output {_output}/avg.pt

  test: >
    python generate.py data-bin/{data} --beam 5 --path {_output}/avg.pt

# default values for all params
default:
  data: iwslt14
  norm: batch
  moment: 0.1
  early-stop: False

# GPU indices to be filled in `CUDA_VISIBLE_DEVICES={}`, each corresponds to a worker.
resource: [ 0, 1, 2, 3 ]

---
# compare the effect of different normalization layer and moment 
norm: [ new, batch ]
moment: [ 0.1, 0.05 ]

---
# examine the effect of early stopping
norm: [ batch ]
early-stop: [ True, False ]

```

Since  `norm=batch,moment=0.1` and `norm=batch,early-stop=False` share the same params, the latter is skipped. As we specify 4 workers each with only one gpu, there are 4 tasks running concurrently:

```
$ run
Orphan params: set()
Tasks: 5, Commands: 15
START   gpu: 0, train: 1/ 4, output/Norm_new-Moment_0.1
START   gpu: 1, train: 2/ 4, output/Norm_new-Moment_0.05
START   gpu: 2, train: 3/ 4, output/Norm_batch-Moment_0.1
START   gpu: 3, train: 4/ 4, output/Norm_batch-Moment_0.05
START   gpu: 0, avg  : 1/ 4, output/Norm_new-Moment_0.1
FAIL    gpu: 0, avg  : 1/ 4, output/Norm_new-Moment_0.1
...
```

The command-line logs are redirected to directories (referred with `{_output}`) of each experiment (named with parameters):

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

We provide `Examiner` as a container to iteratively apply a metric parser to all experiments and aggregate the results. In this example we simply parse the test log for the test BLEU:

```python
from mlrunner.examine import Examiner, latest_log


# define a metric parser for each directory (experiment)
def add_bleu(output_dir, experiment, caches):
    # Each parser follows the same signature
    # It can read/write to a global cache dict `caches`, 
    # and read/write each experiment: 
    # collections.namedtuple("Experiment", ["cache", "metric", "param"])
    latest_test_log = latest_log("test", output_dir)
    bleu = parse_bleu(latest_test_log)  # a user-defined log parser
    experiment.metric["bleu"] = bleu


examiner = Examiner()  # container for parsed results
# register parser for each directory (experiment)
examiner.add(add_bleu)
# run all parsers for directories matched by regex 
examiner.exam(output="output", regex=".*")
# print the tsv table with all (different) params and metrics of each experiment
# return a pandas DataFrame object.
df = examiner.table(print_tsv=True)
```
which results in
```commandline
norm	moment	early-stop	bleu
new	0.1	FALSE	11.0
new	0.05	FALSE	12.3
batch	0.1	FALSE	14.4
batch	0.05	FALSE	16.5
batch	0.1	TRUE	15.0
```
A pandas `DataFrame` object is returned for further analysis.

## Under the hood

A sweep of param combinations results in an ordered task pool. Each param combination is a task. Each worker bound to a `resource` concurrently pulls a task from the pool in order, edits each command in `template`, and executes the commands sequentially. Editions include:

1. Substituting the param placeholders (`{param}` and `[param]`) with corresponding params.
2. Appending shell environment variable `CUDA_VISIBLE_DEVICES={resource}` as the prefix
3. Appending shell redirect `> output_dir/log.{command}.{time} 2>&1` as the suffix

[//]: # (# Workflow)

[//]: # ()
[//]: # (Manually scheduling a **LOT** of experiments can quickly lead to frustrations:)

[//]: # ()
[//]: # (1. Efficiency. During the early phase, we experiment on small models and datasets which are not resource hungry. One can find it hard to fully utilize the GPU times on modern multi-GPU machines.)

[//]: # (2. Cognitive load. There are lengthy pipelines and numerous parameters to tune: data, model architecture, hyperparams, training regimes, and test regimes. These knots are typically scattered in code, data, or command-line args, making the experiment process error-prone and cognitively draining.)

[//]: # (3. Accessibility. How to distinguish artifacts of different experiments in the file system while maintaining readability? How to quickly obtain insights from tens of hundreds of results? How to quickly set up the workflow for new projects?)

[//]: # (4. Robustness: What if your machine is temporally down or some bug happened in your code? Which experiment needs rerun?)

[//]: # ()
[//]: # (This tool tightly integrates into a more effective workflow. In a nutshell:)

[//]: # ()
[//]: # (1. Make every modification &#40;architecture, params, training regime, etc.&#41; adjustable by command line args. This interface is consistent with most code bases.)

[//]: # (    1. For structural changes of models, use if/else or switch/case)

[//]: # (    2. For datasets, specify the directory)

[//]: # (2. Specify irrelevant params in the command template. Make relevant params to the experiment variables &#40;`[param]` or `{param}`&#41; and list values you want to test in a configuration file. Specify default values of these params for reference.)

[//]: # (3. Use a pool of workers to concurrently run all your experiments. Track progress with tools like tensorboard.)

[//]: # (4. Apply the same processing code for each run to parse results you need, and aggregate them for visualization: use tensorboard hyperparams, jupyter notebook, or simply a spreadsheet.)


