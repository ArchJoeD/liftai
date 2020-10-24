from setuptools import setup, find_packages

requirements = []
with open('requirements.txt') as f:
    requirements = f.read().splitlines()


setup(name='liftai-elevation',
      version='0.0.2',
      description=("LiftAi elevation application",
                   "read altimeter data and trip data and determine elevation changes on each trip")[0],
      packages=find_packages(),
      entry_points={
          'console_scripts': [
              'elevation = elevation.main:main',
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
