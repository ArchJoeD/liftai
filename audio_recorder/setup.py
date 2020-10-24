from setuptools import setup, find_packages

requirements = []
with open('requirements.txt') as f:
    requirements = f.read().splitlines()


setup(name='liftai-audio-recorder',
      version='0.0.2',
      description=("LiftAi audio recorder application",
                   "write audio samples from a microphone to specific folder")[0],
      packages=find_packages(),
      entry_points={
          'console_scripts': [
              'audio_recorder = audio_recorder.main:main',
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
