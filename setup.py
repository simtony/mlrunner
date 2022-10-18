import setuptools

setuptools.setup(
        name='mlrunner',
        version='0.5.7',
        author='Tony Ou',
        author_email='simtony2@gmail.com',
        url='https://github.com/simtony/mlrunner',
        description="A light-weight script for maintaining a LOT of machine learning experiments.",
        classifiers=[
            "Programming Language :: Python :: 3",
            "License :: OSI Approved :: MIT License",
            "Operating System :: POSIX :: Linux",
        ],
        install_requires=['pyyaml', 'tabulate', 'ilock', 'pandas'],
        packages=setuptools.find_packages(),
        python_requires='>=3.7',
        entry_points={
            'console_scripts': [
                'run = mlrunner.run:main'
            ]
        }
)
