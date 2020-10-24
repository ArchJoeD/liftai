FROM python:3.5
ENV PYTHONUNBUFFERED 1
RUN mkdir /code
WORKDIR /code

RUN ["apt-get", "update"]
RUN ["apt-get", "install", "-y", "zsh"]
RUN wget https://github.com/robbyrussell/oh-my-zsh/raw/master/tools/install.sh -O - | zsh || true

RUN pip install pylint autopep8 coverage

RUN apt-get update
RUN apt-get install sudo htop lsof net-tools postgresql-client libportaudio2 python-pip3 -y
RUN /usr/bin/python3 -m pip install black

COPY . /code/

# Adapted from travis.yml
RUN pip3 install -e ./utilities
RUN pip3 install -e ./notifications
RUN pip3 install -e ./accelerometer
RUN pip3 install -e ./altimeter
RUN pip3 install -e ./anomaly_detector
RUN pip3 install -e ./audio_recorder
RUN pip3 install -e ./bank_stoppage
RUN pip3 install -e ./data_sender
RUN pip3 install -e ./elevation
RUN pip3 install -e ./elisha
RUN pip3 install -e ./escalator_stoppage
RUN pip3 install -e ./floor_detector
RUN pip3 install -e ./gpio
RUN pip3 install -e ./low_use_stoppage
RUN pip3 install -e ./ping_cloud
RUN pip3 install -e ./report_generator
RUN pip3 install -e ./roawatch
RUN pip3 install -e ./standalone_stoppage
RUN pip3 install -e ./trips
RUN pip3 install -e ./vibration

CMD /bin/sh -c "while sleep 1000; do :; done"