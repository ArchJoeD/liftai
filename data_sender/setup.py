from setuptools import setup, find_packages

requirements = []
with open('requirements.txt') as f:
    requirements = f.read().splitlines()


setup(name='liftai-datasender',
      version='0.0.3',
      description=("LiftAi datasender application",
                   "read data from the DB and POST it to specific URL")[0],
      packages=find_packages(),
      entry_points={
          'console_scripts': [
              'datasender = data_sender.main:main',
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
