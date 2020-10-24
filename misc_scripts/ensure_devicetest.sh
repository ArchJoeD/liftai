#!/usr/bin/env bash

SERVICE_NAME="datasender.service"

sudo rm -fr "/etc/systemd/system/$SERVICE_NAME.d"
sudo mkdir "/etc/systemd/system/$SERVICE_NAME.d"
sudo sh -c "echo \"[Service]\nEnvironment=\\\"LIFTAI_URL=http://devicetest.liftai.com\\\"\" > /etc/systemd/system/$SERVICE_NAME.d/override.conf"
sudo systemctl daemon-reload
sudo systemctl restart $SERVICE_NAME

