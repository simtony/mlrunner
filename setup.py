import setuptools

description = """Maintaining many machine learning experiments requires much manual effort. This lightweight tool helps you currently run a **LOT** of experiments with simple commands and configurations. You can easily aggregate custom metrics for each experiment with a single line of code.

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

See the [github repo](https://github.com/simtony/mlrunner) for example use cases.
"""

setuptools.setup(
        name='mlrunner',
        version='0.5.8',
        author='Tony Ou',
        author_email='simtony2@gmail.com',
        url='https://github.com/simtony/mlrunner',
        description="A light-weight script for maintaining a LOT of machine learning experiments.",
        long_description=description,
        long_description_content_type="text/markdown",
        classifiers=[
            "Programming Language :: Python :: 3",
            "License :: OSI Approved :: MIT License",
            "Operating System :: POSIX :: Linux",
        ],
        install_requires=['pyyaml', 'tabulate', 'ilock', 'pandas', "dill==0.3.6", "multiprocess==0.70.14"],
        packages=setuptools.find_packages(),
        python_requires='>=3.7',
        entry_points={
            'console_scripts': [
                'run = mlrunner.run:main'
            ]
        }
)
