import setuptools

setuptools.setup(
        name='model_tuner',
        version='0.2',
        author='Tony Ou',
        author_email='simtony2@gmail.com',
        url='https://github.com/simtony/tuner',
        description="A light-weight script for launching large number of experiments.",
        classifiers=[
            "Programming Language :: Python :: 3",
            "License :: OSI Approved :: MIT License",
            "Operating System :: POSIX :: Linux",
        ],
        install_requires=['pyyaml'],
        packages=setuptools.find_packages(),
        python_requires='>=3.6.*',
        entry_points={
            'console_scripts': [
                'tune = tuner.tune:main'
            ]
        }
)
