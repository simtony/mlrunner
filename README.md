# Introduction

This is a light-weight script to run multiple experiments in parallel. 
It maintains a task(packaged commands to execute) queue and a pool of workers. 
Each worker is assigned with a number of gpus.
Each worker pulls a task from the queue and run it with assigned resources IN PARALLEL. 

Each task is assigned with a short name corresponding to its parameter choice. The same name is used
to specify the output directory. 
This is by far the best balance between human readability and experiment distinction I have found.

To specify a group of tasks to run, just define valid choices of each parameter in a yaml config file. 
Then the script will sweep all possible combinations and append them to the task queue. 
For large parameter space, you can use random samples from the sweep.
 
I have implemented it with multi-thread and multi-process, but finally settled with asyncio, 
as it is convenient to maintain global resources. 
As the interface of asyncio is still in constant change, this script is only
valid in python 3.6.X, which is a standard version for Nvidia NGC containers. 

# Dependencies
```
python == 3.6.X
pyyaml
```
# Install
Install from source:
```
git pull https://github.com/simtony/model_tuner
cd model_tuner && python3 setup.py install
```

# Usage
Edit the yaml file. Then run
```
tune -o output -c params.yaml
```   
