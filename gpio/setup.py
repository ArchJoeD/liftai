from setuptools import setup, find_packages

requirements = []
with open('requirements.txt') as f:
    requirements = f.read().splitlines()


setup(name='liftai-gpio',
      version='0.0.1',
      description=("LiftAi GPIO application",
                   "read and write general purpose I/O pins connected to the processor")[0],
      packages=find_packages(),
      entry_points={
          'console_scripts': [
              'gpio = gpio.main:main',
          ]
      },
      install_requires=requirements,
      classifiers=(
          'Intended Audience :: Other Audience',
          'Natural Language :: English',
          'License :: Other/Proprietary License',
          'Programming Language :: Python',
          'Programming Language :: Python :: 3.5',
          'Programming Language :: Python :: 3.6',
          'Programming Language :: Python :: Implementation :: CPython',
      ),
      )
