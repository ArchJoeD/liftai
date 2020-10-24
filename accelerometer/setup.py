from setuptools import setup, find_packages

requirements = []
with open('requirements.txt') as f:
    requirements = f.read().splitlines()


setup(name='liftai-accelerometer',
      version='0.0.2',
      description=("LiftAi Accelerometer application",
                   "read data from the MPU6050 sensor and store to DB")[0],
      packages=find_packages(),
      entry_points={
          'console_scripts': [
              'accelerometer = accelerometer.main:main'
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
