import setuptools

setuptools.setup(
        name='runner',
        version='0.5.3.1',
        author='Tony Ou',
        author_email='simtony2@gmail.com',
        url='https://github.com/simtony/runner',
        description="A light-weight script for gpu experiments.",
        classifiers=[
            "Programming Language :: Python :: 3",
            "License :: OSI Approved :: MIT License",
            "Operating System :: POSIX :: Linux",
        ],
        install_requires=['pyyaml', 'tabulate'],
        packages=setuptools.find_packages(),
        python_requires='>=3.6.*',
        entry_points={
            'console_scripts': [
                'run = runner.run:main'
            ]
        }
)
