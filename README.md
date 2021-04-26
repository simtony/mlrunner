# Introduction

This is a light-weight script to run multiple experiments in parallel. 
It maintains a task(packaged commands to execute) queue and a pool of workers. 
Each worker is assigned with a number of gpus.
Each worker pulls a task from the queue and run it with assigned resources IN PARALLEL. 

Each task is assigned with a short name corresponding to its parameter choice. The same name is used
to specify the output directory. 

To specify a group of tasks to run, just define valid choices of each parameter in a yaml config file. 
Then the script will sweep all possible combinations and append them to the task queue. 
For large parameter space, you can use random samples from the sweep.

# Dependencies
```
python >= 3.6.X
pyyaml
```
# Install
```
git pull https://github.com/simtony/runner.git
cd runner && python3 setup.py install
```

# Usage
Edit the yaml file. Then run
```
run -o output -y params.yaml
```   
