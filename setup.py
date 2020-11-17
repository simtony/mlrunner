import setuptools

setuptools.setup(
        name='tuner',
        version='0.1',
        author='Tony Ou',
        description="A light-weight script for launching large number of experiments.",
        classifiers=[
            "Programming Language :: Python :: 3",
            "License :: OSI Approved :: MIT License",
            "Operating System :: POSIX :: Linux",
        ],
        install_requires=['pyyaml'],
        packages=setuptools.find_packages(),
        python_requires='==3.6.*',
        entry_points={
            'console_scripts': [
                'tune=tuner:tune'
            ]
        }
)
