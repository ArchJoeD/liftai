from setuptools import setup, find_packages

requirements = []
with open('requirements.txt') as f:
    requirements = f.read().splitlines()


setup(name='liftai-anomalydetector',
      version='0.0.1',
      description=("LiftAi anomaly detection application",
                   "scan the incoming data for various types of anomalies")[0],
      packages=find_packages(),
      entry_points={
          'console_scripts': [
              'anomalydetector = anomaly_detector.main:main',
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
