from setuptools import setup

requirements = []
with open('requirements.txt') as f:
    requirements = f.read().splitlines()


setup(name='liftai-notifications',
      version='0.0.2',
      description=("LiftAi Notifications Library",
                   "Handles notification management")[0],
      packages=["notifications"],
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

